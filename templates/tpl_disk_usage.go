// tpl_disk_usage.go — Sonda atómica (filesystem): uso de disco del root vía statfs. Sin deps.
package main

import (
	"encoding/json"
	"fmt"
	"syscall"
)

func main() {
	path := "{{path}}"
	if path == "" || path[0] == '{' {
		path = "/"
	}
	var st syscall.Statfs_t
	if err := syscall.Statfs(path, &st); err != nil {
		fmt.Printf("{\"error\":%q}\n", err.Error())
		return
	}
	bs := uint64(st.Bsize)
	total := st.Blocks * bs
	free := st.Bavail * bs
	out := map[string]interface{}{
		"path": path, "total_bytes": total, "free_bytes": free, "used_bytes": total - free,
	}
	b, _ := json.Marshal(out)
	fmt.Println(string(b))
}
