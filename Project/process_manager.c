#define _GNU_SOURCE
#define _POSIX_C_SOURCE 200809L
#include "process_manager.h"
#include "signal_handler.h"
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

typedef struct { pid_t pid; char *command; } Child;
static size_t launched, completed;

static const char *signal_name(int sig) {
    switch (sig) {
        case SIGHUP: return "SIGHUP";
        case SIGINT: return "SIGINT";
        case SIGQUIT: return "SIGQUIT";
        case SIGILL: return "SIGILL";
        case SIGABRT: return "SIGABRT";
        case SIGFPE: return "SIGFPE";
        case SIGKILL: return "SIGKILL";
        case SIGSEGV: return "SIGSEGV";
        case SIGPIPE: return "SIGPIPE";
        case SIGALRM: return "SIGALRM";
        case SIGTERM: return "SIGTERM";
#ifdef SIGBUS
        case SIGBUS: return "SIGBUS";
#endif
#ifdef SIGUSR1
        case SIGUSR1: return "SIGUSR1";
#endif
#ifdef SIGUSR2
        case SIGUSR2: return "SIGUSR2";
#endif
        default: return "UNKNOWN";
    }
}

int process_manager_init(void) { return install_sigchld_handler(); }

static void report_status(pid_t pid, const char *command, int status) {
    printf("\n========================================\nPROCESS TERMINATION MONITOR\n========================================\n\n"
           "Process ID: %ld\nParent Process ID: %ld\nCommand: %s\n", (long)pid, (long)getpid(), command);
    if (WIFEXITED(status)) {
        int code = WEXITSTATUS(status);
        printf("Status: NORMAL\nExit Code: %d\nResult: %s\n", code, code == 0 ? "SUCCESS" : "FAILURE");
    } else if (WIFSIGNALED(status)) {
        int sig = WTERMSIG(status);
        const char *description = strsignal(sig);
        printf("Status: SIGNAL\nSignal Number: %d\nSignal Name: %s (%s)", sig,
               signal_name(sig), description ? description : "unknown");
        printf("\nResult: TERMINATED\n");
#ifdef WCOREDUMP
        printf("Core Dump: %s\n", WCOREDUMP(status) ? "YES" : "NO");
#else
        puts("Core Dump: UNKNOWN (WCOREDUMP unavailable)");
#endif
    }
    puts("\n----------------------------------------"); fflush(stdout);
}

static void reap_children(Child *children, size_t count, size_t *remaining) {
    int status; pid_t pid;
    for (;;) {
        pid = waitpid(-1, &status, WNOHANG);
        if (pid > 0) {
            for (size_t i = 0; i < count; ++i) if (children[i].pid == pid) {
                report_status(pid, children[i].command, status);
                free(children[i].command); children[i].command = NULL;
                if (*remaining) --*remaining;
                ++completed; break;
            }
            continue;
        }
        if (pid < 0 && errno == EINTR) continue;
        break;
    }
    children_changed = 0;
}

static int wait_for_children(Child *children, size_t count, size_t remaining) {
    sigset_t block, old;
    sigemptyset(&block); sigaddset(&block, SIGCHLD);
    if (sigprocmask(SIG_BLOCK, &block, &old) < 0) return -1;
    while (remaining) {
        reap_children(children, count, &remaining);
        if (!remaining) break;
        /* Atomically unblock SIGCHLD while sleeping, avoiding a lost wakeup. */
        sigsuspend(&old);
    }
    if (sigprocmask(SIG_SETMASK, &old, NULL) < 0) return -1;
    return 0;
}

static int launch(const char *command, int test_signal) {
    pid_t pid = fork();
    if (pid < 0) { perror("fork"); return -1; }
    if (pid == 0) {
        if (test_signal) {
            struct sigaction dfl = {0}; dfl.sa_handler = SIG_DFL; sigemptyset(&dfl.sa_mask);
            (void)sigaction(test_signal, &dfl, NULL);
            /* A brief delay lets the parent record the PID before sending the test signal. */
            sleep(1);
            raise(test_signal);
            _exit(128 + test_signal);
        }
        char *const argv[] = { (char *)"sh", (char *)"-c", (char *)command, NULL };
        execvp("sh", argv);
        perror("execvp"); _exit(127);
    }
    return (int)pid;
}

int process_run_commands(const char *const commands[], size_t count) {
    if (!count) return 0;
    Child *children = calloc(count, sizeof(*children));
    if (!children) { perror("calloc"); return -1; }
    sigset_t set, old; sigemptyset(&set); sigaddset(&set, SIGCHLD);
    if (sigprocmask(SIG_BLOCK, &set, &old) < 0) { perror("sigprocmask"); free(children); return -1; }
    size_t started = 0;
    for (size_t i = 0; i < count; ++i) {
        if (!commands[i] || !*commands[i]) { fprintf(stderr, "Skipping empty command.\n"); continue; }
        int result = launch(commands[i], 0);
        if (result < 0) continue;
        children[started].pid = (pid_t)result;
        children[started].command = strdup(commands[i]);
        if (!children[started].command) { perror("strdup"); (void)kill((pid_t)result, SIGTERM); }
        ++started; ++launched;
    }
    if (sigprocmask(SIG_SETMASK, &old, NULL) < 0) perror("sigprocmask");
    size_t tracked = 0;
    for (size_t i = 0; i < started; ++i) if (children[i].command) ++tracked;
    int rc = wait_for_children(children, started, tracked);
    for (size_t i = 0; i < started; ++i) free(children[i].command);
    free(children);
    return rc;
}

int process_test_normal(void) { const char *cmd = "exit 0"; return process_run_commands(&cmd, 1); }

int process_test_signal(int signal_number) {
    Child child = {0};
    sigset_t set, old; sigemptyset(&set); sigaddset(&set, SIGCHLD);
    if (sigprocmask(SIG_BLOCK, &set, &old) < 0) { perror("sigprocmask"); return -1; }
    int pid = launch(NULL, signal_number);
    if (pid < 0) { (void)sigprocmask(SIG_SETMASK, &old, NULL); return -1; }
    child.pid = (pid_t)pid; child.command = strdup(signal_number == SIGTERM ? "test child (SIGTERM)" : "test child (SIGKILL)");
    ++launched;
    (void)sigprocmask(SIG_SETMASK, &old, NULL);
    int rc = wait_for_children(&child, 1, 1);
    free(child.command); return rc;
}

void process_display_info(void) {
    printf("\nParent PID: %ld\nParent's parent PID: %ld\nChildren launched: %zu\nChildren reported: %zu\n",
           (long)getpid(), (long)getppid(), launched, completed);
}
