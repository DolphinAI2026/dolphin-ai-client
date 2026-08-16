package agenticpack

import (
	"bytes"
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"time"

	"github.com/definesys/orcamatrix/agent-runtime/internal/domain"
	"github.com/definesys/orcamatrix/agent-runtime/internal/processutil"
)

const (
	windowsReconcileRetryDelay = 350 * time.Millisecond
	maxReconcileDiagnosticSize = 16 * 1024
)

type CommandReconciler struct {
	packDir   string
	codexHome string
}

func NewCommandReconciler(packDir, codexHome string) CommandReconciler {
	return CommandReconciler{packDir: packDir, codexHome: codexHome}
}

func (r CommandReconciler) Reconcile(ctx context.Context) (domain.AgenticPackReconcileStatus, error) {
	commandPath := filepath.Join(r.packDir, "bin", "agentic-pack-reconcile")
	if runtime.GOOS == "windows" {
		commandPath += ".exe"
	}

	exitCode, stderrText := r.run(ctx, commandPath)
	if runtime.GOOS == "windows" && exitCode == 1 && waitForRetry(ctx) {
		retryExitCode, retryStderr := r.run(ctx, commandPath)
		exitCode = retryExitCode
		stderrText = joinAttemptDiagnostics(stderrText, retryStderr)
	}

	switch exitCode {
	case 0:
		return domain.AgenticPackReconcileStatus{
			Status:   domain.AgenticPackReconcileOK,
			ExitCode: exitCode,
		}, nil
	case 10:
		return domain.AgenticPackReconcileStatus{
			Status:   domain.AgenticPackReconcileDegraded,
			ExitCode: exitCode,
		}, nil
	default:
		writeReconcileDiagnostics(commandPath, stderrText)
		lastError := fmt.Sprintf("agentic pack reconcile command %q failed with exit code %d", commandPath, exitCode)
		if exitCode == 127 {
			if message := strings.TrimSpace(stderrText); message != "" {
				lastError = fmt.Sprintf("%s: %s", lastError, message)
			}
		}
		status := domain.AgenticPackReconcileStatus{
			Status:    domain.AgenticPackReconcileError,
			ExitCode:  exitCode,
			LastError: lastError,
		}
		return status, fmt.Errorf("%s", lastError)
	}
}

func (r CommandReconciler) run(ctx context.Context, commandPath string) (int, string) {
	cmd := processutil.CommandContext(ctx, commandPath, "--codex-home", r.codexHome)
	cmd.WaitDelay = 100 * time.Millisecond
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	err := cmd.Run()
	return exitCode(err), stderr.String()
}

func waitForRetry(ctx context.Context) bool {
	timer := time.NewTimer(windowsReconcileRetryDelay)
	defer timer.Stop()
	select {
	case <-ctx.Done():
		return false
	case <-timer.C:
		return true
	}
}

func joinAttemptDiagnostics(first, second string) string {
	first = strings.TrimSpace(first)
	second = strings.TrimSpace(second)
	switch {
	case first == "":
		return second
	case second == "":
		return first
	default:
		return "first attempt:\n" + first + "\nretry attempt:\n" + second
	}
}

func writeReconcileDiagnostics(commandPath, stderrText string) {
	message := strings.TrimSpace(stderrText)
	if message == "" {
		return
	}
	if len(message) > maxReconcileDiagnosticSize {
		message = message[len(message)-maxReconcileDiagnosticSize:]
	}
	fmt.Fprintf(os.Stderr, "agentic pack reconcile stderr from %q:\n%s\n", commandPath, message)
}

func exitCode(err error) int {
	if err == nil {
		return 0
	}
	if exitErr, ok := err.(*exec.ExitError); ok {
		return exitErr.ExitCode()
	}
	return -1
}
