// Template: tpl_socket_monitor.go
// Category: network
// Description: Sonda atómica en Go para inspección directa de sockets TCP escuchando en el sistema.
// Compilación: CGO_ENABLED=0 go build -ldflags="-s -w" -o socket_monitor tpl_socket_monitor.go

package main

import (
	"bufio"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net"
	"os"
	"strconv"
	"strings"
)

type SocketEntry struct {
	LocalIP    string `json:"local_ip"`
	LocalPort  int    `json:"local_port"`
	RemoteIP   string `json:"remote_ip"`
	RemotePort int    `json:"remote_port"`
	State      string `json:"state"`
	Inode      string `json:"inode"`
}

type Response struct {
	TotalSockets int           `json:"total_sockets"`
	Sockets      []SocketEntry `json:"sockets"`
	Error        string        `json:"error,omitempty"`
}

func parseHexIP(hexIP string) string {
	bytes, err := hex.DecodeString(hexIP)
	if err != nil || len(bytes) != 4 {
		return hexIP
	}
	// /proc/net/tcp almacena la IPv4 en little-endian
	return net.IPv4(bytes[3], bytes[2], bytes[1], bytes[0]).String()
}

func parseHexPort(hexPort string) int {
	port, err := strconv.ParseInt(hexPort, 16, 64)
	if err != nil {
		return 0
	}
	return int(port)
}

func mapTCPState(stateHex string) string {
	states := map[string]string{
		"01": "ESTABLISHED",
		"02": "SYN_SENT",
		"03": "SYN_RECV",
		"04": "FIN_WAIT1",
		"05": "FIN_WAIT2",
		"06": "TIME_WAIT",
		"07": "CLOSE",
		"08": "CLOSE_WAIT",
		"09": "LAST_ACK",
		"0A": "LISTEN",
		"0B": "CLOSING",
	}
	if val, ok := states[stateHex]; ok {
		return val
	}
	return "UNKNOWN"
}

func main() {
	stateFilter := "{{state}}"
	if stateFilter != "" && stateFilter[0] == '{' {
		stateFilter = ""
	}

	resp := Response{Sockets: []SocketEntry{}}

	file, err := os.Open("/proc/net/tcp")
	if err != nil {
		resp.Error = fmt.Sprintf("Error abriendo /proc/net/tcp: %v", err)
		output, _ := json.MarshalIndent(resp, "", "  ")
		fmt.Println(string(output))
		os.Exit(1)
	}
	defer file.Close()

	scanner := bufio.NewScanner(file)
	// Saltar cabecera
	if scanner.Scan() {
		_ = scanner.Text()
	}

	for scanner.Scan() {
		fields := strings.Fields(scanner.Text())
		if len(fields) < 10 {
			continue
		}

		local := strings.Split(fields[1], ":")
		remote := strings.Split(fields[2], ":")
		if len(local) != 2 || len(remote) != 2 {
			continue
		}

		entry := SocketEntry{
			LocalIP:    parseHexIP(local[0]),
			LocalPort:  parseHexPort(local[1]),
			RemoteIP:   parseHexIP(remote[0]),
			RemotePort: parseHexPort(remote[1]),
			State:      mapTCPState(fields[3]),
			Inode:      fields[9],
		}
		if stateFilter != "" && !strings.EqualFold(entry.State, stateFilter) {
			continue
		}
		resp.Sockets = append(resp.Sockets, entry)
	}

	resp.TotalSockets = len(resp.Sockets)
	output, _ := json.MarshalIndent(resp, "", "  ")
	fmt.Println(string(output))
}
