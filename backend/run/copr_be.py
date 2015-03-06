#!/usr/bin/python
# | -ttu

from __future__ import print_function
from __future__ import unicode_literals
from __future__ import division
from __future__ import absolute_import

import optparse
import os
import sys

from bunch import Bunch

from backend.daemons.backend import run_backend


def parse_args(args):
    parser = optparse.OptionParser("\ncopr-be [options]")
    parser.add_option("-c", "--config", default="/etc/copr/copr-be.conf",
                      dest="config_file",
                      help="config file to use for copr-be run")
    parser.add_option("-d", "--daemonize", default=False, dest="daemonize",
                      action="store_true", help="daemonize or not")
    parser.add_option("-p", "--pidfile",
                      default="/var/run/copr-backend/copr-be.pid",
                      dest="pidfile",
                      help="pid file to use for copr-be if daemonized")
    parser.add_option("-x", "--exit", default=False, dest="exit_on_worker",
                      action="store_true", help="exit on worker failure")
    parser.add_option("-v", "--verbose", default=False, dest="verbose",
                      action="store_true", help="be more verbose")

    opts, args = parser.parse_args(args)
    if not os.path.exists(opts.config_file):
        sys.stderr.write("No config file found at: {0}\n".format(
            opts.config_file))
        sys.exit(1)
    opts.config_file = os.path.abspath(opts.config_file)

    ret_opts = Bunch()
    for o in ("daemonize", "exit_on_worker", "pidfile", "config_file"):
        setattr(ret_opts, o, getattr(opts, o))

    return ret_opts


def main(args):
    opts = parse_args(args)
    run_backend(opts)

if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except KeyboardInterrupt:
        sys.stderr.write("\nUser cancelled, may need cleanup\n")
        sys.exit(0)
