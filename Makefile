build:
	GOOS=linux GOARCH=amd64 go build -o /tmp/checkbox main.go
run:
	go run main.go 

