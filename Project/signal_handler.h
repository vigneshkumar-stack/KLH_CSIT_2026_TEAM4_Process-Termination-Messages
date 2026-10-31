#ifndef SIGNAL_HANDLER_H
#define SIGNAL_HANDLER_H
#include <signal.h>
extern volatile sig_atomic_t children_changed;
int install_sigchld_handler(void);
#endif
