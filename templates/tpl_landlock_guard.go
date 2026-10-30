// Template: tpl_landlock_guard.go
// Category: security
// Description: Sonda estática en Go para auditar soporte y confinamiento de Landlock LSM (Kernel 5.13+).
// Compilación: CGO_ENABLED=0 go build -ldflags="-s -w" -o landlock-guard main.go

package main

import (
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"syscall"
	"unsafe"
)

const (
	SYS_PRCTL                       = 157
	PR_SET_NO_NEW_PRIVS             = 38
	SYS_LANDLOCK_CREATE_RULESET     = 444
	SYS_LANDLOCK_ADD_RULE           = 445
	SYS_LANDLOCK_RESTRICT_SELF      = 446
	LANDLOCK_CREATE_RULESET_VERSION = 1 << 0
	LANDLOCK_RULE_PATH_BENEATH      = 1
	FULL_FS_ACCESS_V1               = (1 << 13) - 1
)

type LandlockRulesetAttr struct {
	HandledAccessFS uint64
}

type LandlockPathBeneathAttr struct {
	AllowedAccess uint64
	ParentFD      int32
}

type Response struct {
	Status              string `json:"status"`
	Probe               string `json:"probe"`
	Supported           bool   `json:"supported"`
	ABIVersion          int    `json:"abi_version"`
	EnforcementVerified bool   `json:"enforcement_verified"`
	Error               string `json:"error,omitempty"`
}

func queryABIVersion() (int, error) {
	ret, _, err := syscall.Syscall6(
		SYS_LANDLOCK_CREATE_RULESET,
		0,
		0,
		LANDLOCK_CREATE_RULESET_VERSION,
		0,
		0,
		0,
	)
	if int(ret) <= 0 {
		return 0, err
	}
	return int(ret), nil
}

func runChildEnforcement(tmpDir string) int {
	attr := LandlockRulesetAttr{
		HandledAccessFS: FULL_FS_ACCESS_V1,
	}
	rulesetFD, _, _ := syscall.Syscall6(
		SYS_LANDLOCK_CREATE_RULESET,
		uintptr(unsafe.Pointer(&attr)),
		unsafe.Sizeof(attr),
		0,
		0,
		0,
		0,
	)
	if int(rulesetFD) < 0 {
		return 10
	}
	defer func() { _ = syscall.Close(int(rulesetFD)) }()

	fd, errOpen := syscall.Open(tmpDir, syscall.O_RDONLY|syscall.O_CLOEXEC, 0)
	if errOpen != nil {
		return 11
	}
	beneath := LandlockPathBeneathAttr{
		AllowedAccess: FULL_FS_ACCESS_V1,
		ParentFD:      int32(fd),
	}
	retAdd, _, _ := syscall.Syscall6(
		SYS_LANDLOCK_ADD_RULE,
		rulesetFD,
		LANDLOCK_RULE_PATH_BENEATH,
		uintptr(unsafe.Pointer(&beneath)),
		0,
		0,
		0,
	)
	_ = syscall.Close(fd)
	if retAdd != 0 {
		return 12
	}

	retPrctl, _, _ := syscall.Syscall6(
		SYS_PRCTL,
		PR_SET_NO_NEW_PRIVS,
		1,
		0,
		0,
		0,
		0,
	)
	if retPrctl != 0 {
		return 13
	}

	retRestrict, _, _ := syscall.Syscall6(
		SYS_LANDLOCK_RESTRICT_SELF,
		rulesetFD,
		0,
		0,
		0,
		0,
		0,
	)
	if retRestrict != 0 {
		return 14
	}

	// 1. Escritura en ruta permitida (debe triunfar)
	allowedFile := filepath.Join(tmpDir, "allowed.txt")
	if errWrite := os.WriteFile(allowedFile, []byte("ok"), 0644); errWrite != nil {
		return 15
	}

	// 2. Escritura en ruta no permitida (debe fallar con EACCES/EPERM)
	blockedFile := filepath.Join(os.TempDir(), fmt.Sprintf("landlock_blocked_%d.txt", os.Getpid()))
	if errBlocked := os.WriteFile(blockedFile, []byte("fail"), 0644); errBlocked == nil {
		_ = os.Remove(blockedFile)
		return 16 // Falla: permitió escribir en ruta no autorizada
	}

	return 0 // Éxito: confinamiento verificado
}

func main() {
	if len(os.Args) > 2 && os.Args[1] == "--child" {
		code := runChildEnforcement(os.Args[2])
		os.Exit(code)
	}

	resp := Response{
		Status: "OK",
		Probe:  "landlock-guard",
	}

	abi, err := queryABIVersion()
	if err != nil || abi <= 0 {
		resp.Status = "DEGRADED"
		resp.Supported = false
		resp.ABIVersion = 0
		resp.EnforcementVerified = false
		if err != nil {
			resp.Error = err.Error()
		} else {
			resp.Error = "Landlock ABI version <= 0"
		}
		data, _ := json.MarshalIndent(resp, "", "  ")
		fmt.Println(string(data))
		return
	}

	resp.Supported = true
	resp.ABIVersion = abi

	// Test de confinamiento aislado en subproceso
	tmpDir, errTmp := os.MkdirTemp("", "landlock_guard_*")
	if errTmp != nil {
		resp.EnforcementVerified = false
		resp.Error = fmt.Sprintf("Error creating tempdir: %v", errTmp)
		data, _ := json.MarshalIndent(resp, "", "  ")
		fmt.Println(string(data))
		return
	}
	defer func() { _ = os.RemoveAll(tmpDir) }()

	exePath := "/proc/self/exe"
	if _, errStat := os.Stat(exePath); errStat != nil {
		if p, errExe := os.Executable(); errExe == nil {
			exePath = p
		} else {
			exePath = os.Args[0]
		}
	}

	// nosemgrep: go.lang.security.audit.dangerous-exec-command.dangerous-exec-command
	cmd := exec.Command(exePath, "--child", tmpDir)
	if errRun := cmd.Run(); errRun == nil {
		resp.EnforcementVerified = true
	} else {
		resp.EnforcementVerified = false
		resp.Error = fmt.Sprintf("Child confinement probe failed: %v", errRun)
	}

	data, _ := json.MarshalIndent(resp, "", "  ")
	fmt.Println(string(data))
}
