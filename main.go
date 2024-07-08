package main

import (
	"context"
	"crypto/tls"
	"embed"
	"encoding/base64"
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"log/slog"
	"math"
	"math/rand"
	"net"
	"net/http"
	"os"
	"runtime/debug"
	"sync/atomic"
	"time"
	"strconv"
	
	"github.com/gin-contrib/static"
	"github.com/redis/go-redis/v9"
	"github.com/zishang520/socket.io/v2/socket"

	"github.com/alicebob/miniredis/v2"
	"github.com/gin-gonic/gin"
	"github.com/puzpuzpuz/xsync"
)

var (
	background           = context.Background()
	mini                 *miniredis.Miniredis
	primaryRedisClient   *redis.Client
	secondaryRedisClient *redis.Client
	port                 = flag.Int("port", 5001, "http port to listen to")
	logChannel           = make(chan *toggleLogEntry, 20)
	activeConns          atomic.Int64
	REDIS_SECONDARY_IP   = flag.String(
		"redis-secondary",
		"10.108.0.15",
		"",
	)
	forceStateSnapshot = flag.Duration(
		"force-snapshot-interval",
		time.Second*50,
		"",
	)
	maxLogInterval  = flag.Duration("max-log-interval", time.Second*5, "")
	maxLogBatchSize = flag.Int("max-log-batch", 200, "")
	mercyRatio      = flag.Int64(
		"mercy-ratio",
		1,
		"how quickly we should forgive the bad guys",
	)
)

//go:embed dist
var distFolder embed.FS

const (
	MAX_LOGS_PER_DAY = 400_000_000
	TOTAL_CHECKBOXES = 1_000_000
)

func initRedis() {
	log := slog.With("scope", "redis")
	if os.Getenv("REDIS_HOST") == "" {
		primaryRedisClient = miniClient()
		secondaryRedisClient = primaryRedisClient
	} else {
		p, err := primaryRedis()
		if err != nil {
			log.Error("Unable to talk to primary redis", "err", err)
		}
		s, err := replicaRedis()
		if err != nil {
			log.Error("Unable to talk to secondary redis", "err", err)
		}
		primaryRedisClient = p
		secondaryRedisClient = s
	}
	err := newSetBitScript.Load(background, primaryRedisClient).Err()
	if err != nil {
		log.Error("Unable to load scripts into primary redis, %s", err)
	}
	err = newSetBitScript.Load(background, secondaryRedisClient).Err()
	if err != nil {
		log.Error("Unable to load scripts into secondary redis, %s", err)
	}
	// if err := primaryRedisClient.SetNX(
	// 	background,
	// 	"truncated_bitset",
	// 	string(make([]byte, TOTAL_CHECKBOXES)),
	// 	0,
	// ).Err(); err != nil {
	// 	log.Error("Unable to initialize bitset %s", err)
	// }
	if err := primaryRedisClient.SetNX(
		background,
		"sunset_bitset",
		string(make([]byte, TOTAL_CHECKBOXES)),
		0,
	).Err(); err != nil {
		log.Error("Unable to initialize sunset bitset %s", err)
	}
	if err := primaryRedisClient.SetNX(
		background,
		"sunset_count",
		"1000000",
		0,
	).Err(); err != nil {
		log.Error("Unable to initialize sunset count %s", err)
	}
	if err := primaryRedisClient.SetNX(
		background,
		"frozen_bitset",
		string(make([]byte, TOTAL_CHECKBOXES)),
		0,
	).Err(); err != nil {
		log.Error("Unable to initialize frozen bitset %s", err)
	}
	if err := primaryRedisClient.SetNX(
		background,
		"freeze_time_ms",
		"1000",
		0,
	).Err(); err != nil {
		log.Error("Unable to initialize freeze time %s", err)
	}
	if err := primaryRedisClient.SetNX(
		background,
		"frozen_count",
		"0",
		0,
	).Err(); err != nil {
		log.Error("Unable to initialize frozen count %s", err)
	}
}

type stateSnapshot struct {
	FullState string `json:"full_state"`
	FrozenState string `json:"frozen_state"`
	Count     int    `json:"count"`
	FrozenCount int `json:"frozen_count"`
	Timestamp int    `json:"timestamp"`
}

func JSON(v any) string {
	buff, err := json.Marshal(v)
	if err != nil {
		slog.Error("Bad json ", "err", err)
		return "{}"
	}
	return string(buff)
}

func getStateSnapshot() *stateSnapshot {
	count, _ := secondaryRedisClient.Get(background, "sunset_count").Int()
	frozenCount, _ := secondaryRedisClient.Get(background, "frozen_count").Int()
	return &stateSnapshot{
		FullState: getFullState(),
		FrozenState: getFrozenState(),
		Count:     count,
		FrozenCount: frozenCount,
		Timestamp: int(time.Now().UnixMilli()),
	}
}

type toggleLogEntry struct {
	ip    string
	index int
	state bool
}

func logToggles(logs []*toggleLogEntry) {
	now := time.Now()
	key := fmt.Sprintf(
		"checkbox_logs:%s",
		now.Format(time.DateOnly),
	)
	pipeline := primaryRedisClient.Pipeline()
	t := "True"
	f := "False"
	for _, l := range logs {
		state := t
		if !l.state {
			state = f
		}

		entry := fmt.Sprintf(
			"%s|%s|%d|%s|new",
			now.Format(time.DateTime),
			l.ip,
			l.index,
			state,
		)
		pipeline.RPush(background, key, entry)
	}

	pipeline.LTrim(background, key, 0, int64(MAX_LOGS_PER_DAY-1))
	_, err := pipeline.Exec(background)
	if err != nil {
		slog.Error("error during redis log rotation", "err", err)
	}
}
func catch(f func(), cleanup ...func()) {
	defer func() {
		if msg := recover(); msg != nil {
			slog.Error("Recovered from panic %v", msg)
			debug.PrintStack()
			for _, c := range cleanup {
				catch(c)
			}
		}
	}()
	f()
}

func tryForever(f func()) {

	for {
		catch(f)
	}
}

func try(f func(args ...any)) func(...any) {
	return func(args ...any) {
		catch(func() {
			f(args...)
		})
	}
}

func handleLogs() {
	tryForever(func() {
		t := time.NewTicker(*maxLogInterval)
		var buff []*toggleLogEntry
		for {
			select {
			case <-t.C:
				if len(buff) == 0 {
					continue
				}
			case msg := <-logChannel:
				buff = append(buff, msg)
				if len(buff) < *maxLogBatchSize {
					continue
				}
			}
			abuseCount := 0
			activeClientCount := 0
			abuseMap.Range(func(key string, value *atomic.Int64) bool {
				abuseCount += int(value.Load())
				activeClientCount += 1
				return true
			})
			slog.Info(
				"submitting logs",
				"count",
				len(buff),
				"clients",
				activeClientCount,
				"totalAbuse",
				abuseCount,
			)
			logToggles(buff)
			buff = buff[:0]
		}
	})
}

var (
	abuseMap = xsync.NewMapOf[*atomic.Int64]()
)

var (
	maxAbuseRequests = flag.Int64(
		"max-abuse-requests",
		500,
		"maximum nubmer of requests a client can make before we consider it abuse",
	)
	abuseResetInterval = flag.Duration(
		"abuse-reset",
		time.Minute,
		"reset the abuse pentaly after this time",
	)
)
func groupIPv6(ip string) (string, bool) {

	parsedIP := net.ParseIP(ip)
	if parsedIP == nil || parsedIP.To4() != nil {
		return ip, false // Return as-is if it's not a valid IPv6 address
	}

	ipv6Addr := parsedIP.To16()
	if ipv6Addr == nil {
		return ip, false // Shouldn't happen, but just in case
	}

	// Keep the first 48 bits (6 bytes) and zero out the rest
	// maybe 64?
	for i := 8; i < 16; i++ {
		ipv6Addr[i] = 0
	}

	return ipv6Addr.String(), true
}

func socketIP(s *socket.Socket) (string, bool) {
	// Check Cloudflare-specific header first
	log := slog.With("socketIP")
	NOLEN_IP := s.Request().Request().Header.Get("NOLEN-IP")
	
	cfIP := s.Request().Request().Header.Get("CF-Connecting-IP")
	
	if NOLEN_IP != "" {
		// check if it begins with "10."
		if len(NOLEN_IP) < 3 || NOLEN_IP[:3] == "10." {
			log.Info("SKIP NOLEN IP ITS PRIVATE");
		} else {
			log.Info("Using NOLEN IP", "ip", NOLEN_IP)
			return groupIPv6(NOLEN_IP);
		}
	}

	
	if cfIP != "" {
		log.Info("Using Cloudflare IP", "ip", cfIP)
		return groupIPv6(cfIP);
	}
	forwarded := s.Request().Request().Header.Get("X-Forwarded-For")
	if forwarded != "" {
		log.Info("Using forwarded IP", "ip", forwarded)
		return groupIPv6(forwarded);

	}

	addr, _ := net.ResolveTCPAddr("tcp", s.Conn().RemoteAddress())
	z := addr.IP.String()
	log.Info("Using remote IP", "ip", z)
	return groupIPv6(z);
}

func resetAbuseCounters() {
	tryForever(func() {
		t := time.NewTicker(*abuseResetInterval)
		zeros := []string{}
		for range t.C {
			abuseMap.Range(func(key string, value *atomic.Int64) bool {
				tmp := value.Load()
				tmp -= (*maxAbuseRequests * *mercyRatio)
				if tmp < 0 {
					zeros = append(zeros, key)
					value.Store(0)
					return true
				}
				value.Store(tmp)
				return true
			})
		}

		for _, name := range zeros {
			abuseMap.Delete(name)
		}
	})
}

func detectAbuse(ip string, isIPV6 bool) bool {
	count, _ := abuseMap.LoadOrCompute(ip, func() *atomic.Int64 {
		v := new(atomic.Int64)
		v.Store(0)
		return v
	})
	if isIPV6 {
		// count.Add(50)
		count.Add(1)
	} else {
		count.Add(1)
	}
	if count.Load() < *maxAbuseRequests {
		return false
	}
	// reducing this a bit to trim load a little more
	thousands := float64(count.Load()) / 750
	chance := math.Pow(0.5, thousands)
	return chance > rand.Float64()
}

func dumpHashsetState(rdb *redis.Client, log *slog.Logger) {
    result, err := rdb.HGetAll(context.Background(), "last_checked").Result()
    if err != nil {
        log.Error("Failed to get hashset state", "error", err)
        return
    }

    state := make(map[string]int64)
    for k, v := range result {
        timestamp, err := strconv.ParseInt(v, 10, 64)
        if err != nil {
            log.Error("Failed to parse timestamp", "key", k, "value", v, "error", err)
            continue
        }
        state[k] = timestamp
    }

    stateJSON, err := json.MarshalIndent(state, "", "  ")
    if err != nil {
        log.Error("Failed to marshal hashset state", "error", err)
        return
    }

    log.Info("Current hashset state", "state", string(stateJSON))
}

func main() {
	flag.Parse()
	initRedis()
	r := gin.Default()
	r.Group("/api").GET("/initial-state", func(ctx *gin.Context) {
		ctx.JSON(200,
			getStateSnapshot(),
		)
	})
	go resetAbuseCounters()
	defer primaryRedisClient.Close()
	defer secondaryRedisClient.Close()
	go handleLogs()

	ws := socket.NewServer(nil, nil)
	ws.On("connection", func(a ...any) {
		client := a[0].(*socket.Socket)
		catch(func() {
			ip, isIPV6 := socketIP(client)
			activeConns.Add(1)
			log := slog.With(
				"client",
				client.Id(),
				"ip",
				ip,
				"isIPV6",
				isIPV6,
			)
			if (isIPV6) {
				// add socket to "ipv6" room
				client.Join("ipv6")
			}
			client.On("disconnect", try(func(a ...any) {
				activeConns.Add(-1)
				log.Debug("leaving")
			}))
			if detectAbuse(ip, isIPV6) {
				log.Info("rejecting connection from suspected abuse ip")
				client.Conn().Close(true)
				return
			}

			client.On("toggle_bit", try(func(a ...any) {
				if detectAbuse(ip, isIPV6) {
					client.Conn().Close(true)
					log.Info("rejecting toggle from suspected abuse ip")
					return
				}
				data := a[0].(map[string]any)
				index := int(data["index"].(float64))
				tlg := log.WithGroup("toggle_bit").With("index", index)
				if (index >= TOTAL_CHECKBOXES || index < 0) {
					log.Error("attmepted to toggle bad index")
					return
				}
				res := frozenSetBitScript.Run(
					background,
					primaryRedisClient,
					[]string{
						"sunset_bitset",
						"sunset_count",
						"frozen_bitset",
						"frozen_count",
						"freeze_time_ms",
					},
					int(index),
					TOTAL_CHECKBOXES,
				)
				if res.Err() != nil {
					tlg.Error("Unable to toggle bit", "err", res.Err())
					return
				}
				ts := time.Now().UnixMilli()
				nv, _ := res.Int64Slice()
				nbv, diff, newly_frozen := nv[0], nv[1], nv[2]
				log.Info("toggled bit", "index", index, "new_value", nbv, "newly_frozen", newly_frozen)
				dumpHashsetState(primaryRedisClient, log)
				if diff != 0 {
					tlg.Debug("toggled bit")

					logChannel <- &toggleLogEntry{
						ip:    ip,
						index: index,
						state: nbv > 0,
					}
					primaryRedisClient.Publish(
						background,
						"bit_toggle_channel",
						JSON([]any{
							index, int(nbv), ts,
						}),
					)
				}
				if newly_frozen == 1 {
					tlg.Debug("frozen bit")
					primaryRedisClient.Publish(
						background,
						"frozen_bit_channel",
						JSON([]any{
							index, ts,
						}),
					)
				}
			}))
			slog.Debug("New connection", "socket", a)
		}, func() {
			client.Disconnect(true)
		})
	})

	go func() {
		tryForever(func() {
			t := time.NewTicker(*forceStateSnapshot)
			log := slog.With("scope", "forceStateSnapshot")
			for range t.C {
				log.Debug("starting snapshot send")
				ws.Except("ipv6").Emit("full_state", getStateSnapshot())
				log.Debug("compete snapshot send")
			}
		})
	}()

	go func() {
		tryForever(func() {
			maxBatchSize := 400
			ticker := time.NewTicker(time.Second / 10)
			subscriber := secondaryRedisClient.Subscribe(
				background,
				"bit_toggle_channel",
			)
			defer subscriber.Close()
			log := slog.With("subscriber", subscriber)

			messages := subscriber.Channel()
			changed := make(map[int]bool, maxBatchSize)
			maxTs := 0
			tmp := make([]int, 3)

			emitAll := func() {
				on := make([]int, 0, len(changed)/2)
				off := make([]int, 0, len(changed)/2)
				for k, v := range changed {
					if v {
						on = append(on, k)
						log.Info("on", "index", k)
					} else {
						off = append(off, k)
						log.Info("off", "index", k)
					}
				}
				ws.Except().Emit("batched_bit_toggles", []any{on, off, maxTs})
				log.Debug("emmitting", "on", on, "off", off)
				changed = make(map[int]bool, maxBatchSize)
				maxTs = 0
			}
			for {
				select {
				case msg := <-messages:
					json.Unmarshal([]byte(msg.Payload), &tmp)
					index, nbv, ts := tmp[0], tmp[1], tmp[2]
					changed[index] = nbv > 0
					maxTs = max(ts, maxTs)
					if len(changed) < maxBatchSize {
						continue
					}
				case <-ticker.C:
					if len(changed) == 0 {
						continue
					}
				}

				catch(emitAll)
			}
		})
	}()

	go func() {
		tryForever(func() {
			maxBatchSize := 400
			ticker := time.NewTicker(time.Second / 7)
			subscriber := secondaryRedisClient.Subscribe(
				background,
				"frozen_bit_channel",
			)
			defer subscriber.Close()
			log := slog.With("subscriber", subscriber)

			messages := subscriber.Channel()
			frozen := make([]int, 0, maxBatchSize)
			maxTs := 0
			tmp := make([]int, 2)

			emitAll := func() {
				ws.Except().Emit("batched_frozen_bits", []any{frozen, maxTs})
				log.Debug("emmitting", "frozen", frozen)
				frozen = make([]int, 0, maxBatchSize)
				maxTs = 0
			}
			for {
				select {
				case msg := <-messages:
					json.Unmarshal([]byte(msg.Payload), &tmp)
					index, ts := tmp[0], tmp[1]
					frozen = append(frozen, index)
					maxTs = max(ts, maxTs)
					if len(frozen) < maxBatchSize {
						continue
					}
				case <-ticker.C:
					if len(frozen) == 0 {
						continue
					}
				}

				catch(emitAll)
			}
		})
	}()

	wss := ws.ServeHandler(nil)
	gin.WrapF(func(w http.ResponseWriter, r *http.Request) {
		ip := "";
		NOLEN_IP := r.Header.Get("NOLEN-IP")
		cfIP := r.Header.Get("CF-Connecting-IP")
		forwarded := r.Header.Get("X-Forwarded-For")
		if NOLEN_IP != "" {
			ip = NOLEN_IP;
		} else if cfIP != "" {
			ip = cfIP;
		} else if forwarded != "" {
			ip = forwarded;
		} else {
			ip = "10.0.0.1";
		}
		parsedIp, isIPV6 := groupIPv6(ip)

		if detectAbuse(parsedIp, isIPV6) {
			slog.With("ip", forwarded).
				Info("Rejecting http reqeust from suspected abuse ip")
			w.WriteHeader(400)
			return
		}

		wss.ServeHTTP(w, r)
	})

	h := gin.WrapH(ws.ServeHandler(nil))
	r.GET("/socket.io/", h)
	r.POST("/socket.io/", h)
	r.NoRoute(static.Serve("/", static.EmbedFolder(distFolder, "dist")))
	go r.Run(
		fmt.Sprintf(":%d", *port),
	)
	go r.Run(
		fmt.Sprintf(":%d", *port+1),
	)
	go r.Run(
		fmt.Sprintf(":%d", *port+2),
	)
	r.Run(
		fmt.Sprintf(":%d", *port+3),
	)
}

func envOr(name, def string) string {
	s := os.Getenv(name)
	if s == "" {
		return def
	}
	return s
}
func miniClient() *redis.Client {
	if mini == nil {
		mini = miniredis.NewMiniRedis()
		mini.Start()
	}
	client := redis.NewClient(&redis.Options{
		Addr: mini.Addr(),
	})
	if ping := client.Ping(background); ping.Err() != nil {
		log.Fatalf("Unable to estable connection to miniredis %s", ping.Err())
	}
	return client

}
func primaryRedis() (*redis.Client, error) {
	return redisClient(
		envOr("REDIS_HOST", "localhost"),
		envOr("REDIS_PORT", "6379"),
		envOr("REDIS_USERNAME", "default"),
		envOr("REDIS_PASSWORD", ""),
	)
}
func replicaRedis() (*redis.Client, error) {
	return redisClient(
		*REDIS_SECONDARY_IP,
		envOr("REDIS_PORT", "6379"),
		envOr("REDIS_USERNAME", "default"),
		envOr("REDIS_PASSWORD", ""),
	)
}

func getFullState() string {

	buff, err := secondaryRedisClient.Get(background, "sunset_bitset").
		Bytes()
	if err != nil {
		log.Panicf("Unable to read bitset from redis", err)
	}
	return base64.RawStdEncoding.EncodeToString(buff)
}

func getFrozenState() string {
	buff, err := secondaryRedisClient.Get(background, "frozen_bitset").
		Bytes()
	if err != nil {
		log.Panicf("Unable to read frozen bitset from redis", err)
	}
	return base64.StdEncoding.EncodeToString(buff)
}

func redisClient(host, port, user, pass string) (*redis.Client, error) {
	rdb := redis.NewClient(&redis.Options{
		Addr: fmt.Sprintf(
			"%s:%s",
			host, port,
		),
		Username:              user,
		Password:              pass, // no password set
		DB:                    0,    // use default DB
		MaxIdleConns:          20,
		MaxActiveConns:        40,
		DialTimeout:           time.Second * 10,
		ContextTimeoutEnabled: true,
		// PoolTimeout:    time.Second * 1,
		TLSConfig: &tls.Config{
			InsecureSkipVerify: true,
		},
	})
	return rdb, rdb.Ping(background).Err()
}

// redis scripts
var (
	setBitScript = redis.NewScript(`
local key = KEYS[1]
local index = tonumber(ARGV[1])
local value = tonumber(ARGV[2])
local current = redis.call('getbit', key, index)
local diff = value - current
redis.call('setbit', key, index, value)
redis.call('incrby', 'count', diff)
return diff`)

	newSetBitScript = redis.NewScript(`
local key = KEYS[1]
local count_key = KEYS[2]
local index = tonumber(ARGV[1])
local max_count = tonumber(ARGV[2])

local current_count = tonumber(redis.call('get', count_key) or "0")
if current_count >= max_count then
	return {redis.call('getbit', key, index), 0}  -- Return current count, current bit value, and 0 to indicate no change
end

local current_bit = redis.call('getbit', key, index)
local new_bit = 1 - current_bit  -- Toggle the bit
local diff = new_bit - current_bit

if diff > 0 and current_count + diff > max_count then
	return { current_bit, 0}  -- Return current count, current bit value, and 0 to indicate no change
end

redis.call('setbit', key, index, new_bit)
local new_count = current_count + diff
redis.call('set', count_key, new_count)

return {new_bit, diff}  -- new bit value, and the change (1, 0, or -1)`)

frozenSetBitScript = redis.NewScript(`
local bitset_key = KEYS[1]
local count_key = KEYS[2]
local frozen_bitset_key = KEYS[3]
local frozen_count_key = KEYS[4]
local freeze_time_key = KEYS[5]
local index = tonumber(ARGV[1])
local max_count = tonumber(ARGV[2])

-- Sentinel value for unchecked boxes (0 is a good choice as it's falsy in Lua)
local UNCHECKED_SENTINEL = 0

-- Get current Redis time in milliseconds
local redis_time = redis.call('TIME')
local current_time = tonumber(redis_time[1]) * 1000 + math.floor(tonumber(redis_time[2]) / 1000)

-- Get freeze_time from Redis (in milliseconds)
local freeze_time = tonumber(redis.call('get', freeze_time_key) or "0")

-- Get current state
local current_count = tonumber(redis.call('get', count_key) or "0")
local current_bit = redis.call('getbit', bitset_key, index)
local frozen_bit = redis.call('getbit', frozen_bitset_key, index)

-- Check if the box is already frozen
if frozen_bit == 1 then
    return {current_bit, 0, 0}  -- Return current bit value, 0 for no change, and 1 to indicate frozen
end

-- If we're at max count, no changes allowed
if current_count >= max_count then
    return {current_bit, 0, 0}
end

-- Toggle the bit
local new_bit = 1 - current_bit
local diff = new_bit - current_bit

-- If we're unchecking (new_bit == 0), check the freeze_time
if new_bit == 0 then
    local last_checked = tonumber(redis.call('hget', 'last_checked', index) or UNCHECKED_SENTINEL)
    if last_checked ~= UNCHECKED_SENTINEL and current_time - last_checked >= freeze_time then
        -- Box is frozen, update frozen bitset and count
        redis.call('setbit', frozen_bitset_key, index, 1)
        redis.call('incr', frozen_count_key)
        return {1, 0, 1}  -- Return 1 (checked), 0 for no change, and 1 to indicate newly frozen
    else
        -- Set the sentinel value instead of deleting
        redis.call('hset', 'last_checked', index, UNCHECKED_SENTINEL)
    end
else
    -- We're checking the box, update last_checked time
    redis.call('hset', 'last_checked', index, current_time)
end

-- Proceed with the change
redis.call('setbit', bitset_key, index, new_bit)
local new_count = current_count + diff
redis.call('set', count_key, new_count)

return {new_bit, diff, 0}  -- new bit value, the change (-1, 0, or 1), and 0 to indicate not frozen`)
)
