// tpl_mem_stat.go — Sonda atómica (memory): lectura de /proc/meminfo a JSON tipado. Sin deps.
package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"strconv"
	"strings"
)

func main() {
	f, err := os.Open("/proc/meminfo")
	if err != nil {
		fmt.Printf("{\"error\":%q}\n", err.Error())
		return
	}
	defer func() { _ = f.Close() }()
	mem := map[string]int64{}
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		parts := strings.Fields(sc.Text())
		if len(parts) >= 2 {
			key := strings.TrimSuffix(parts[0], ":")
			if v, e := strconv.ParseInt(parts[1], 10, 64); e == nil {
				mem[key] = v * 1024
			}
		}
	}
	out := map[string]interface{}{
		"total_bytes": mem["MemTotal"], "free_bytes": mem["MemFree"], "available_bytes": mem["MemAvailable"],
	}
	b, _ := json.Marshal(out)
	fmt.Println(string(b))
}
