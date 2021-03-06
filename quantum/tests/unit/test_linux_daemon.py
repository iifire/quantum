# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright 2012 New Dream Network, LLC (DreamHost)
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
#
# @author: Mark McClain, DreamHost

import os

import mock
import unittest2 as unittest

from quantum.agent.linux import daemon

FAKE_FD = 8


class TestPidfile(unittest.TestCase):
    def setUp(self):
        self.os_p = mock.patch.object(daemon, 'os')
        self.os = self.os_p.start()
        self.os.open.return_value = FAKE_FD

        self.fcntl_p = mock.patch.object(daemon, 'fcntl')
        self.fcntl = self.fcntl_p.start()
        self.fcntl.flock.return_value = 0

    def tearDown(self):
        self.fcntl_p.stop()
        self.os_p.stop()

    def test_init(self):
        self.os.O_CREAT = os.O_CREAT
        self.os.O_RDWR = os.O_RDWR

        p = daemon.Pidfile('thefile', 'python')
        self.os.open.assert_called_once_with('thefile', os.O_CREAT | os.O_RDWR)
        self.fcntl.flock.assert_called_once_with(FAKE_FD, self.fcntl.LOCK_EX)

    def test_init_open_fail(self):
        self.os.open.side_effect = IOError

        with mock.patch.object(daemon.sys, 'stderr') as stderr:
            with self.assertRaises(SystemExit):
                p = daemon.Pidfile('thefile', 'python')
                sys.assert_has_calls([
                    mock.call.stderr.write(mock.ANY),
                    mock.call.exit(1)]
                )

    def test_unlock(self):
        p = daemon.Pidfile('thefile', 'python')
        p.unlock()
        self.fcntl.flock.assert_has_calls([
            mock.call(FAKE_FD, self.fcntl.LOCK_EX),
            mock.call(FAKE_FD, self.fcntl.LOCK_UN)]
        )

    def test_write(self):
        p = daemon.Pidfile('thefile', 'python')
        p.write(34)

        self.os.assert_has_calls([
            mock.call.ftruncate(FAKE_FD, 0),
            mock.call.write(FAKE_FD, '34'),
            mock.call.fsync(FAKE_FD)]
        )

    def test_read(self):
        self.os.read.return_value = '34'
        p = daemon.Pidfile('thefile', 'python')
        self.assertEqual(34, p.read())

    def test_is_running(self):
        with mock.patch('quantum.agent.linux.utils.execute') as execute:
            execute.return_value = 'python'
            p = daemon.Pidfile('thefile', 'python')

            with mock.patch.object(p, 'read') as read:
                read.return_value = 34
                self.assertTrue(p.is_running())

            execute.assert_called_once_with(
                ['cat', '/proc/34/cmdline'], 'sudo')


class TestDaemon(unittest.TestCase):
    def setUp(self):
        self.os_p = mock.patch.object(daemon, 'os')
        self.os = self.os_p.start()

        self.pidfile_p = mock.patch.object(daemon, 'Pidfile')
        self.pidfile = self.pidfile_p.start()

    def tearDown(self):
        self.pidfile_p.stop()
        self.os_p.stop()

    def test_init(self):
        d = daemon.Daemon('pidfile')
        self.assertEqual(d.procname, 'python')

    def test_fork_parent(self):
        self.os.fork.return_value = 1
        with self.assertRaises(SystemExit):
            d = daemon.Daemon('pidfile')
            d._fork()

    def test_fork_child(self):
        self.os.fork.return_value = 0
        d = daemon.Daemon('pidfile')
        self.assertIsNone(d._fork())

    def test_fork_error(self):
        self.os.fork.side_effect = lambda: OSError(1)
        with mock.patch.object(daemon.sys, 'stderr') as stderr:
            with self.assertRaises(SystemExit):
                d = daemon.Daemon('pidfile', 'stdin')
                d._fork()

    def test_daemonize(self):
        d = daemon.Daemon('pidfile')
        with mock.patch.object(d, '_fork') as fork:
            with mock.patch.object(daemon, 'atexit') as atexit:
                with mock.patch.object(daemon, 'sys') as sys:
                    sys.stdin.fileno.return_value = 0
                    sys.stdout.fileno.return_value = 1
                    sys.stderr.fileno.return_value = 2
                    d.daemonize()
                    atexit.register.assert_called_once_with(d.delete_pid)

            fork.assert_has_calls([mock.call(), mock.call()])

        self.os.assert_has_calls([
            mock.call.chdir('/'),
            mock.call.setsid(),
            mock.call.umask(0),
            mock.call.dup2(mock.ANY, 0),
            mock.call.dup2(mock.ANY, 1),
            mock.call.dup2(mock.ANY, 2),
            mock.call.getpid()]
        )

    def test_delete_pid(self):
        self.pidfile.return_value.__str__.return_value = 'pidfile'
        d = daemon.Daemon('pidfile')
        d.delete_pid()
        self.os.remove.assert_called_once_with('pidfile')

    def test_start(self):
        self.pidfile.return_value.is_running.return_value = False
        d = daemon.Daemon('pidfile')

        with mock.patch.object(d, 'daemonize') as daemonize:
            with mock.patch.object(d, 'run') as run:
                d.start()
                run.assert_called_once_with()
                daemonize.assert_called_once_with()

    def test_start_running(self):
        self.pidfile.return_value.is_running.return_value = True
        d = daemon.Daemon('pidfile')

        with mock.patch.object(daemon.sys, 'stderr') as stderr:
            with mock.patch.object(d, 'daemonize') as daemonize:
                with self.assertRaises(SystemExit):
                    d.start()
                self.assertFalse(daemonize.called)
