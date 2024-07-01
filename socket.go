package main

import (
	"github.com/zishang520/socket.io/v2/socket"
)

func socketIOHandler() *socket.Server {
	server := socket.NewServer(nil, nil)
	return server
}
