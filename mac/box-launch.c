// box-launch <command> [args...]: run a command as a child and wait for it.
//
// macOS asks before a launchd job reads ~/Documents (TCC), and it asks about the binary launchd
// started, by path. The T3 service binary moves to a new versioned path on every `t3 update`, so
// each update raised a fresh prompt on the box's screen and agents hung until someone clicked.
// launchd starts this binary instead; it stays the parent, so T3, the reapers, the heartbeat and
// everything they spawn are attributed to this one fixed path, and one grant lasts.
//
// Don't rebuild it casually: the grant is tied to this build's signature (install-macbox only
// compiles it when it's missing).
#include <errno.h>
#include <signal.h>
#include <spawn.h>
#include <stdio.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

extern char **environ;
static volatile pid_t child = 0;

static void forward(int sig) {
  if (child > 0) kill(child, sig);
}

int main(int argc, char **argv) {
  if (argc < 2) {
    fprintf(stderr, "usage: box-launch <command> [args...]\n");
    return 64;
  }
  struct sigaction sa;
  memset(&sa, 0, sizeof sa);
  sa.sa_handler = forward;
  sigemptyset(&sa.sa_mask);
  int sigs[] = {SIGTERM, SIGINT, SIGHUP, SIGQUIT, SIGUSR1, SIGUSR2};
  for (size_t i = 0; i < sizeof sigs / sizeof sigs[0]; i++) sigaction(sigs[i], &sa, NULL);

  pid_t pid;
  int rc = posix_spawnp(&pid, argv[1], NULL, NULL, argv + 1, environ);
  if (rc != 0) {
    fprintf(stderr, "box-launch: %s: %s\n", argv[1], strerror(rc));
    return 127;
  }
  child = pid;

  int status;
  while (waitpid(pid, &status, 0) < 0) {
    if (errno != EINTR) return 1;
  }
  if (WIFEXITED(status)) return WEXITSTATUS(status);
  if (WIFSIGNALED(status)) {
    // Die the same way, so launchd sees what happened to the real program.
    signal(WTERMSIG(status), SIG_DFL);
    kill(getpid(), WTERMSIG(status));
  }
  return 1;
}
