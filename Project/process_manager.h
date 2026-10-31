#ifndef PROCESS_MANAGER_H
#define PROCESS_MANAGER_H
#include <signal.h>
#include <stddef.h>
int process_manager_init(void);
int process_run_commands(const char *const commands[], size_t count);
int process_test_normal(void);
int process_test_signal(int signal_number);
void process_display_info(void);
#endif
