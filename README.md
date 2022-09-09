# kanboard-taskwarrior
Sync tasks between a local [taskwarrior](https://taskwarrior.org) instance and an online [Kanboard](https://kanboard.org/) instance. 
Note: this is an experimental version, it has limited functionality and I can't garantee it does not accidentally loses tasks


# Installation
To install the script you can directly install it using `pip` from github
`pip install git+https://github.com/strawpants/kanboard_taskwarrior.git`

This will install a python module together with a command line script `taskync.py`

# Configuration
In order to synchronize a Kanboard project, a synchronization link must be registered first. You can take the following steps below
1. If you haven't doen so, set up a Kanboard project on your Kanboard server
2. Generate an API token on the Kanboard server by clicking at the top right the arrow next to your user avatar and select `My Profile->API-> generate a new token`
3. [Install and setup Taskwarrior](https://taskwarrior.org/docs/start/) on your local computer
4. Run `tasksync.py -c ProjectName` where ProjectName is the name of your Kanboard project (it will also be the name of the Taskwarrior project`
5. Follow the interactive instructions from the `tasksync.py` script to assign a mapping between your Kanboard project and Taskwarrior instance

You can then synchronize tasks at will by running `tasksync.py -s`

Note: the configuration and state of the synchronization is stored in a sqlite database `~/.task/taskw-sync-KB.sql`

## Running as a service
The `tasksync.py` script can also be run as a daeomon service which sychronizes the tasks at regular intervals (using the `-d` option). A [service file](tasksync.service) is provided which can be run as a user service upon login:
1. copy `tasksync.py` to `~/.config/systemd/user/` 
2. enable the user service `systemctl --user enable tasksync`
3. start the service `systemctl --user start tasksync`


# Command line usage
Some help can be listed by executing `tasksync.py -h`:

```
usage: tasksync.py [-h] [-c] [-s] [-d [SECONDS]] [-t] [-r] [-p] [-l] [-v] [Project]

Program to synchronize kanboard and taskwarrrior tasks

positional arguments:
  Project               Specify specific project to apply the actions to (default takes all)

options:
  -h, --help            show this help message and exit
  -c, --config          Configure/modify kanboard-taskwarrior connections
  -s, --sync            Synchronize the registered connections
  -d [SECONDS], --daemonize [SECONDS]
                        Run the syncing operation as a service (default checks once every hour)
  -t, --test            Report the actions which a sync would do but do not actually execute them
  -r, --remove          Remove a project link from the database, this does not delete actual tasks
  -p, --purge           Purge dangling tasks (deleted in either taskwarrior or kanboard)
  -l, --list            List configured couplings
  -v, --verbose         Increase verbosity (more -v's mean an increased verbosity)
```

# TODO
* Thorough checking of functionality during daily use
* Improve mapping of tasks tw <-> kb (e.g. tags are currently not yet synchronized)
* Better conflict resolving (if tasks are modified on both sides)

