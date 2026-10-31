#define _POSIX_C_SOURCE 200809L
#include "signal_handler.h"
#include <stddef.h>

volatile sig_atomic_t children_changed = 0;

static void on_sigchld(int signo) {
    (void)signo;
    children_changed = 1;
}

int install_sigchld_handler(void) {
    struct sigaction action = {0};
    action.sa_handler = on_sigchld;
    sigemptyset(&action.sa_mask);
    action.sa_flags = SA_NOCLDSTOP;
    return sigaction(SIGCHLD, &action, NULL);
}
