// Template: tpl_fd_rescuer.go
// Category: process
// Description: Sonda atómica en Go para inspección no-invasiva de descriptores de archivo (/proc/$PID/fd)
// Uso: ./fd_rescuer <PID>
// Compilación: CGO_ENABLED=0 go build -ldflags="-s -w" -o fd_rescuer tpl_fd_rescuer.go

package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
)

type FDEntry struct {
	FD     int    `json:"fd"`
	Target string `json:"target"`
	Type   string `json:"type"`
}

type FDResponse struct {
	PID     int       `json:"pid"`
	TotalFD int       `json:"total_fd"`
	Entries []FDEntry `json:"entries"`
	Error   string    `json:"error,omitempty"`
}

func classifyTarget(target string) string {
	switch {
	case len(target) >= 7 && target[:7] == "socket:":
		return "socket"
	case len(target) >= 5 && target[:5] == "pipe:":
		return "pipe"
	case len(target) >= 5 && target[:5] == "/dev/":
		return "device"
	case len(target) >= 9 && target[:9] == "anon_inode":
		return "anon_inode"
	default:
		return "file"
	}
}

func main() {
	resp := FDResponse{Entries: []FDEntry{}}

	defaultPID := "{{pid}}"
	argPID := defaultPID
	if len(os.Args) >= 2 {
		argPID = os.Args[1]
	}

	if argPID == "" || argPID[0] == '{' || argPID == "0" {
		resp.Error = "Debe proporcionar un PID como argumento o hidratar {{pid}}. Uso: ./fd_rescuer <PID>"
		out, _ := json.MarshalIndent(resp, "", "  ")
		fmt.Println(string(out))
		os.Exit(1)
	}

	pid, err := strconv.Atoi(argPID)
	if err != nil {
		resp.Error = fmt.Sprintf("PID inválido: %s", os.Args[1])
		out, _ := json.MarshalIndent(resp, "", "  ")
		fmt.Println(string(out))
		os.Exit(1)
	}
	resp.PID = pid

	fdDir := fmt.Sprintf("/proc/%d/fd", pid)
	files, err := os.ReadDir(fdDir)
	if err != nil {
		resp.Error = fmt.Sprintf("No se pudo leer %s: %v", fdDir, err)
		out, _ := json.MarshalIndent(resp, "", "  ")
		fmt.Println(string(out))
		os.Exit(1)
	}

	for _, file := range files {
		fdNum, err := strconv.Atoi(file.Name())
		if err != nil {
			continue
		}

		fullPath := filepath.Join(fdDir, file.Name())
		target, err := os.Readlink(fullPath)
		if err != nil {
			target = "unreadable"
		}

		resp.Entries = append(resp.Entries, FDEntry{
			FD:     fdNum,
			Target: target,
			Type:   classifyTarget(target),
		})
	}

	resp.TotalFD = len(resp.Entries)
	out, _ := json.MarshalIndent(resp, "", "  ")
	fmt.Println(string(out))
}
