# kanboard-taskwarrior
Sync tasks between a local taskwarrior installation and an online kanboard instance


# Usage
```
usage: tasksync.py [-h] [-c] [-s] [-d [SECONDS]] [-t] [-l] [-v] [Project]

Program to synchronize kanboard and taskwarrrior tasks

positional arguments:
  Project               Specify specific project to apply the actions to (default takes all)

options:
  -h, --help            show this help message and exit
  -c, --config          Configure/modify kanboard-taskwarrior connections
  -s, --sync            Synchronize the registered connections
  -d [SECONDS], --daemonize [SECONDS]
                        Run the syncing operation as a service (default checks once every 180 seconds)
  -t, --test            Report the actions which a sync would do but do not actually execute them
  -l, --list            List configured couplings
  -v, --verbose         Increase verbosity (more -v's mean an increased verbosity)
```
