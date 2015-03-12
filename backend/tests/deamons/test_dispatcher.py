import json
import multiprocessing
import os
import pprint
from subprocess import CalledProcessError

from ansible.errors import AnsibleError
from bunch import Bunch
import pytest
import tempfile
import shutil
import time

import six

from backend.constants import BuildStatus, JOB_GRAB_TASK_END_PUBSUB
from backend.exceptions import CoprWorkerError, CoprSpawnFailError, MockRemoteError, NoVmAvailable, VmError
from backend.job import BuildJob
from backend.vm_manage.models import VmDescriptor

if six.PY3:
    from unittest import mock
    from unittest.mock import MagicMock
else:
    import mock
    from mock import MagicMock


from backend.daemons.dispatcher import Worker, WorkerCallback

STDOUT = "stdout"
STDERR = "stderr"
COPR_OWNER = "copr_owner"
COPR_NAME = "copr_name"
COPR_VENDOR = "vendor"

MODULE_REF = "backend.daemons.dispatcher"

@pytest.yield_fixture
def mc_register_build_result(*args, **kwargs):
    patcher = mock.patch("{}.register_build_result".format(MODULE_REF))
    obj = patcher.start()
    yield obj
    patcher.stop()


@pytest.yield_fixture
def mc_run_ans():
    with mock.patch("{}.run_ansible_playbook".format(MODULE_REF)) as handle:
        yield handle


@pytest.yield_fixture
def mc_mr_class():
    with mock.patch("{}.MockRemote".format(MODULE_REF)) as handle:
        yield handle


@pytest.yield_fixture
def mc_time():
    with mock.patch("{}.time".format(MODULE_REF)) as handle:
        yield handle


@pytest.yield_fixture
def mc_grc():
    with mock.patch("{}.get_redis_connection".format(MODULE_REF)) as handle:
        yield handle


@pytest.yield_fixture
def mc_setproctitle():
    with mock.patch("{}.setproctitle".format(MODULE_REF)) as handle:
        yield handle


class TestDispatcher(object):

    def setup_method(self, method):
        self.test_time = time.time()
        subdir = "test_createrepo_{}".format(time.time())
        self.tmp_dir_path = os.path.join(tempfile.gettempdir(), subdir)
        os.mkdir(self.tmp_dir_path)

        self.pkg_pdn = "foobar"
        self.pkg_name = "{}.src.rpm".format(self.pkg_pdn)
        self.pkg_path = os.path.join(self.tmp_dir_path, self.pkg_name)
        with open(self.pkg_path, "w") as handle:
            handle.write("1")

        self.CHROOT = "fedora-20-x86_64"
        self.vm_ip = "192.168.1.2"
        self.vm_name = "VM_{}".format(self.test_time)

        self.DESTDIR = os.path.join(self.tmp_dir_path, COPR_OWNER, COPR_NAME)
        self.DESTDIR_CHROOT = os.path.join(self.DESTDIR, self.CHROOT)
        self.FRONT_URL = "htt://front.example.com"
        self.BASE_URL = "http://example.com/results"
        self.PKG_NAME = "foobar"
        self.PKG_VERSION = "1.2.3"
        self.HOST = "127.0.0.1"
        self.SRC_PKG_URL = "http://example.com/{}-{}.src.rpm".format(self.PKG_NAME, self.PKG_VERSION)
        self.job_build_id = 12345
        self.task = {
            "project_owner": COPR_OWNER,
            "project_name": COPR_NAME,
            "pkgs": self.SRC_PKG_URL,
            "repos": "",
            "build_id": self.job_build_id,
            "chroot": self.CHROOT,
            "task_id": "{}-{}".format(self.job_build_id, self.CHROOT)
        }

        self.spawn_pb = "/spawn.yml"
        self.terminate_pb = "/terminate.yml"
        self.opts = Bunch(
            ssh=Bunch(transport="paramiko"),
            spawn_in_advance=False,
            frontend_url="http://example.com/",
            frontend_auth="12345678",
            build_groups={
                "3": {
                    "spawn_playbook": self.spawn_pb,
                    "terminate_playbook": self.terminate_pb,
                    "name": "3"
                }
            },
            terminate_vars=[],

            fedmsg_enabled=False,
            sleeptime=0.1,
            do_sign=True,
            worker_logdir=self.tmp_dir_path,
            timeout=1800,
            destdir=self.tmp_dir_path,
            results_baseurl="/tmp",

            consecutive_failure_threshold=10,
        )
        self.job = BuildJob(self.task, self.opts)

        self.try_spawn_args = '-c ssh {}'.format(self.spawn_pb)

        self.worker_num = 2
        self.group_id = "3"
        self.events = multiprocessing.Queue()
        self.ip = "192.168.1.1"
        self.worker_callback = MagicMock()
        self.events = multiprocessing.Queue()
        self.logfile_path = os.path.join(self.tmp_dir_path, "test.log")

        self.frontend_client = MagicMock()

    @pytest.yield_fixture
    def mc_vmm(self):
        with mock.patch("{}.VmManager".format(MODULE_REF)) as handle:
            self.vmm = MagicMock()
            handle.return_value = self.vmm
            yield self.vmm

    @pytest.fixture
    def init_worker(self):
        self.worker = Worker(
            opts=self.opts,
            events=self.events,
            frontend_client=self.frontend_client,
            worker_num=self.worker_num,
            group_id=self.group_id,
            callback=self.worker_callback,
        )

        self.worker.vmm = MagicMock()


        def set_ip(*args, **kwargs):
            self.worker.vm_ip = self.vm_ip

        def erase_ip(*args, **kwargs):
            self.worker.vm_ip = None

        self.set_ip = set_ip
        self.erase_ip = erase_ip

    @pytest.fixture
    def reg_vm(self):
        # call only with init_worker fixture
        self.worker.vm_name = self.vm_name
        self.worker.vm_ip = self.vm_ip

    def teardown_method(self, method):
        # print("\nremove: {}".format(self.tmp_dir_path))
        shutil.rmtree(self.tmp_dir_path)

    def test_init_worker_wo_callback(self):
        worker = Worker(
            opts=self.opts,
            events=self.events,
            frontend_client=self.frontend_client,
            worker_num=self.worker_num,
            group_id=self.group_id,
        )
        worker.vmm = MagicMock()
        assert worker.callback

    def test_pkg_built_before(self):
        assert not Worker.pkg_built_before(self.pkg_path, self.CHROOT, self.tmp_dir_path)
        target_dir = os.path.join(self.tmp_dir_path, self.CHROOT, self.pkg_pdn)
        os.makedirs(target_dir)
        assert not Worker.pkg_built_before(self.pkg_path, self.CHROOT, self.tmp_dir_path)
        with open(os.path.join(target_dir, "fail"), "w") as handle:
            handle.write("undone")
        assert not Worker.pkg_built_before(self.pkg_path, self.CHROOT, self.tmp_dir_path)
        os.remove(os.path.join(target_dir, "fail"))
        with open(os.path.join(target_dir, "success"), "w") as handle:
            handle.write("done")
        assert Worker.pkg_built_before(self.pkg_path, self.CHROOT, self.tmp_dir_path)

    @mock.patch("backend.daemons.dispatcher.fedmsg")
    def test_event(self, mc_fedmsg, init_worker):
        template = "foo: {foo}, bar: {bar}"
        content = {"foo": "foo", "bar": "bar"}
        topic = "copr_test"

        self.worker.opts.fedmsg_enabled = True
        self.worker.event(topic, template, content)
        el = self.worker.events.get()

        assert el["who"] == "worker-2"
        assert el["what"] == "foo: foo, bar: bar"

    @mock.patch("backend.daemons.dispatcher.fedmsg")
    def test_event_error(self, mc_fedmsg, init_worker):
        template = "foo: {foo}, bar: {bar}"
        content = {"foo": "foo", "bar": "bar"}
        topic = "copr_test"
        mc_fedmsg.publish.side_effect = IOError()

        self.worker.opts.fedmsg_enabled = True
        self.worker.event(topic, template, content)
        el = self.worker.events.get()

        assert el["who"] == "worker-2"
        assert el["what"] == "foo: foo, bar: bar"

    @mock.patch("backend.daemons.dispatcher.fedmsg")
    def test_event_disable_fedmsg(self, mc_fedmsg, init_worker):
        template = "foo: {foo}, bar: {bar}"
        content = {"foo": "foo", "bar": "bar"}
        topic = "copr_test"
        mc_fedmsg.publish.side_effect = IOError()

        self.worker.event(topic, template, content)
        assert not mc_fedmsg.publish.called

    def test_worker_callback(self):
        wc = WorkerCallback(self.logfile_path)

        assert not os.path.exists(self.logfile_path)
        msg = "foobar"
        wc.log(msg)

        with open(self.logfile_path) as handle:
            obtained = handle.read()
            assert msg in obtained

    @mock.patch("backend.daemons.dispatcher.open", create=True)
    def test_worker_callback_error(self, mc_open, capsys):
        wc = WorkerCallback(self.logfile_path)
        mc_open.side_effect = IOError()

        wc.log("foobar")
        stdout, stderr = capsys.readouterr()

        assert "Could not write to logfile" in stderr

        assert not os.path.exists(self.logfile_path)

    def test_mark_started(self, init_worker):
        self.worker.mark_started(self.job)

        expected_call = mock.call({'builds': [
            {'status': 3, 'build_id': self.job_build_id,
             'project_name': 'copr_name', 'submitter': None,
             'project_owner': 'copr_owner', 'repos': [],
             'results': u'/tmp/copr_owner/copr_name/',
             'destdir': self.DESTDIR,
             'started_on': None, 'submitted_on': None, 'chroot': 'fedora-20-x86_64',
             'ended_on': None, 'built_packages': '', 'timeout': 1800, 'pkg_version': '',
             'pkg_epoch': None, 'pkg_main_version': '', 'pkg_release': None,
             'memory_reqs': None, 'buildroot_pkgs': None, 'id': self.job_build_id,
             'pkg': self.SRC_PKG_URL, "enable_net": True,
             'task_id': self.job.task_id, 'mockchain_macros': {
                'copr_username': 'copr_owner',
                'copr_projectname': 'copr_name',
                'vendor': 'Fedora Project COPR (copr_owner/copr_name)'}
             }
        ]})
        assert expected_call == self.frontend_client.update.call_args

    def test_mark_started_error(self, init_worker):
        self.frontend_client.update.side_effect = IOError()

        with pytest.raises(CoprWorkerError):
            self.worker.mark_started(self.job)

    def test_return_results(self, init_worker):
        self.job.started_on = self.test_time
        self.job.ended_on = self.test_time + 10

        self.worker.mark_started(self.job)

        expected_call = mock.call({'builds': [
            {'status': 3, 'build_id': self.job_build_id,
             'project_name': 'copr_name', 'submitter': None,
             'project_owner': 'copr_owner', 'repos': [],
             'results': u'/tmp/copr_owner/copr_name/',
             'destdir': self.DESTDIR,
             'started_on': self.job.started_on, 'submitted_on': None, 'chroot': 'fedora-20-x86_64',
             'ended_on': self.job.ended_on, 'built_packages': '', 'timeout': 1800, 'pkg_version': '',
             'pkg_epoch': None, 'pkg_main_version': '', 'pkg_release': None,
             'memory_reqs': None, 'buildroot_pkgs': None, 'id': self.job_build_id,
             'pkg': self.SRC_PKG_URL, "enable_net": True,
             'task_id': self.job.task_id, 'mockchain_macros': {
                'copr_username': 'copr_owner',
                'copr_projectname': 'copr_name',
                'vendor': 'Fedora Project COPR (copr_owner/copr_name)'}
             }
        ]})

        assert expected_call == self.frontend_client.update.call_args

    def test_return_results_error(self, init_worker):
        self.job.started_on = self.test_time
        self.job.ended_on = self.test_time + 10
        self.frontend_client.update.side_effect = IOError()

        with pytest.raises(CoprWorkerError):
            self.worker.return_results(self.job)

    def test_starting_builds(self, init_worker):
        self.job.started_on = self.test_time
        self.job.ended_on = self.test_time + 10

        self.worker.starting_build(self.job)

        expected_call = mock.call(self.job_build_id, self.CHROOT)
        assert expected_call == self.frontend_client.starting_build.call_args

    def test_starting_build_error(self, init_worker):
        self.frontend_client.starting_build.side_effect = IOError()

        with pytest.raises(CoprWorkerError):
            self.worker.starting_build(self.job)

    @mock.patch("backend.daemons.dispatcher.MockRemote")
    @mock.patch("backend.daemons.dispatcher.os")
    def test_do_job_failure_on_mkdirs(self, mc_os, mc_mr, init_worker, reg_vm):
        mc_os.path.exists.return_value = False
        mc_os.makedirs.side_effect = IOError()

        self.worker.do_job(self.job)
        assert self.job.status == BuildStatus.FAILURE
        assert not mc_mr.called

    def test_do_job(self, mc_mr_class, init_worker, reg_vm, mc_register_build_result):
        assert not os.path.exists(self.DESTDIR_CHROOT)

        self.worker.do_job(self.job)
        assert self.job.status == BuildStatus.SUCCEEDED
        assert os.path.exists(self.DESTDIR_CHROOT)

    def test_do_job_updates_details(self, mc_mr_class, init_worker, reg_vm, mc_register_build_result):
        assert not os.path.exists(self.DESTDIR_CHROOT)
        mc_mr_class.return_value.build_pkg_and_process_results.return_value = {
            "results": self.test_time,
        }

        self.worker.do_job(self.job)
        assert self.job.status == BuildStatus.SUCCEEDED
        assert self.job.results == self.test_time
        assert os.path.exists(self.DESTDIR_CHROOT)

    def test_do_job_mr_error(self, mc_mr_class, init_worker,
                             reg_vm, mc_register_build_result):
        mc_mr_class.return_value.build_pkg_and_process_results.side_effect = MockRemoteError("foobar")

        self.worker.do_job(self.job)
        assert self.job.status == BuildStatus.FAILURE

    @mock.patch("backend.daemons.dispatcher.fedmsg")
    def test_init_fedmsg(self, mc_fedmsg, init_worker):
        self.worker.init_fedmsg()
        assert not mc_fedmsg.init.called
        self.worker.opts.fedmsg_enabled = True
        self.worker.init_fedmsg()
        assert mc_fedmsg.init.called

        mc_fedmsg.init.side_effect = KeyError()
        self.worker.init_fedmsg()

    def test_obtain_job(self, init_worker):
        mc_tq = MagicMock()
        self.worker.task_queue = mc_tq
        self.worker.starting_build = MagicMock()
        self.worker.pkg_built_before = MagicMock()
        self.worker.pkg_built_before.return_value = False

        mc_tq.dequeue.return_value = MagicMock(data=self.task)
        obtained_job = self.worker.obtain_job()
        assert obtained_job.__dict__ == self.job.__dict__
        assert self.worker.pkg_built_before.called

    def test_obtain_job_skip_pkg(self, init_worker):
        mc_tq = MagicMock()
        self.worker.task_queue = mc_tq
        self.worker.starting_build = MagicMock()
        self.worker.pkg_built_before = MagicMock()
        self.worker.pkg_built_before.return_value = True
        self.worker.mark_started = MagicMock()
        self.worker.return_results = MagicMock()

        self.worker.notify_job_grab_about_task_end = MagicMock()

        mc_tq.dequeue.return_value = MagicMock(data=self.task)
        assert self.worker.obtain_job() is None
        assert self.worker.pkg_built_before.called
        assert self.worker.notify_job_grab_about_task_end.called

    def test_obtain_job_dequeue_type_error(self, init_worker):
        mc_tq = MagicMock()
        self.worker.task_queue = mc_tq
        self.worker.starting_build = MagicMock()
        self.worker.pkg_built_before = MagicMock()
        self.worker.pkg_built_before.return_value = False

        mc_tq.dequeue.side_effect = TypeError()
        assert self.worker.obtain_job() is None
        assert not self.worker.starting_build.called
        assert not self.worker.pkg_built_before.called

    def test_obtain_job_dequeue_none_result(self, init_worker):
        mc_tq = MagicMock()
        self.worker.task_queue = mc_tq
        self.worker.starting_build = MagicMock()
        self.worker.pkg_built_before = MagicMock()
        self.worker.pkg_built_before.return_value = False

        mc_tq.dequeue.return_value = None
        assert self.worker.obtain_job() is None
        assert not self.worker.starting_build.called
        assert not self.worker.pkg_built_before.called

    def test_obtain_job_on_starting_build(self, init_worker):
        mc_tq = MagicMock()
        self.worker.task_queue = mc_tq
        self.worker.starting_build = MagicMock()
        self.worker.starting_build.return_value = False
        self.worker.pkg_built_before = MagicMock()
        self.worker.pkg_built_before.return_value = False

        mc_tq.dequeue.return_value = MagicMock(data=self.task)
        assert self.worker.obtain_job() is None
        assert not self.worker.pkg_built_before.called

    def test_dummy_run(self, init_worker, mc_time, mc_grc):
        self.worker.init_fedmsg = MagicMock()
        self.worker.run_cycle = MagicMock()
        self.worker.update_process_title = MagicMock()

        def on_run_cycle(*args, **kwargs):
            self.worker.kill_received = True

        self.worker.run_cycle.side_effect = on_run_cycle
        self.worker.run()

        assert self.worker.init_fedmsg.called
        assert self.worker.vmm.post_init.called

        assert mc_grc.called
        assert self.worker.run_cycle.called

    def test_group_name_error(self, init_worker):
        self.opts.build_groups[self.group_id].pop("name")
        assert self.worker.group_name == str(self.group_id)

    def test_update_process_title(self, init_worker, mc_setproctitle):
        self.worker.update_process_title()
        base_title = 'worker-{} {} '.format(self.group_id, self.worker_num)
        assert mc_setproctitle.call_args[0][0] == base_title

        #mc_setproctitle.reset_mock()
        self.worker.vm_ip = self.vm_ip
        self.worker.update_process_title()
        title_with_ip = base_title + "VM_IP={} ".format(self.vm_ip)
        assert mc_setproctitle.call_args[0][0] == title_with_ip

        self.worker.vm_name = self.vm_name
        self.worker.update_process_title()
        title_with_name = title_with_ip + "VM_NAME={} ".format(self.vm_name)
        assert mc_setproctitle.call_args[0][0] == title_with_name

        self.worker.update_process_title("foobar")
        assert mc_setproctitle.call_args[0][0] == title_with_name + "foobar"

    def test_dummy_notify_job_grab_about_task_end(self, init_worker):
        self.worker.rc = MagicMock()
        self.worker.notify_job_grab_about_task_end(self.job)
        expected = json.dumps({
            "action": "remove",
            "build_id": 12345,
            "chroot": "fedora-20-x86_64",
            "task_id": "12345-fedora-20-x86_64"
        })
        assert self.worker.rc.publish.call_args == mock.call(JOB_GRAB_TASK_END_PUBSUB, expected)

        self.worker.notify_job_grab_about_task_end(self.job, True)
        expected2 = json.dumps({
            "action": "reschedule",
            "build_id": 12345,
            "chroot": "fedora-20-x86_64",
            "task_id": "12345-fedora-20-x86_64"
        })
        assert self.worker.rc.publish.call_args == mock.call(JOB_GRAB_TASK_END_PUBSUB, expected2)

    def test_run_cycle(self, init_worker, mc_time):
        self.worker.update_process_title = MagicMock()
        self.worker.obtain_job = MagicMock()
        self.worker.do_job = MagicMock()
        self.worker.notify_job_grab_about_task_end = MagicMock()

        self.worker.obtain_job.return_value = None
        self.worker.run_cycle()
        assert self.worker.obtain_job.called
        assert mc_time.sleep.called
        assert not mc_time.time.called

        vmd = VmDescriptor(self.vm_ip, self.vm_name, 0, "ready")
        vmd.vm_ip = self.vm_ip
        vmd.vm_name = self.vm_name

        self.worker.obtain_job.return_value = self.job
        self.worker.vmm.acquire_vm.side_effect = [
            IOError(),
            None,
            NoVmAvailable("foobar"),
            vmd,
        ]

        self.worker.run_cycle()
        assert not self.worker.do_job.called
        assert self.worker.notify_job_grab_about_task_end.called_once
        assert self.worker.notify_job_grab_about_task_end.call_args[1]["do_reschedule"]
        self.worker.notify_job_grab_about_task_end.reset_mock()

        ###  normal work
        def on_release_vm(*args, **kwargs):
            assert self.worker.vm_ip == self.vm_ip
            assert self.worker.vm_name == self.vm_name

        self.worker.vmm.release_vm.side_effect = on_release_vm
        self.worker.run_cycle()
        assert self.worker.do_job.called_once
        assert self.worker.notify_job_grab_about_task_end.called_once
        assert not self.worker.notify_job_grab_about_task_end.call_args[1].get("do_reschedule")

        assert self.worker.vmm.release_vm.called

        self.worker.vmm.acquire_vm = MagicMock()
        self.worker.vmm.acquire_vm.return_value = vmd

        ### handle VmError
        self.worker.notify_job_grab_about_task_end.reset_mock()
        self.worker.vmm.release_vm.reset_mock()
        self.worker.do_job.side_effect = VmError("foobar")
        self.worker.run_cycle()

        assert self.worker.notify_job_grab_about_task_end.call_args[1]["do_reschedule"]
        assert self.worker.vmm.release_vm.called


        ### handle other errors
        self.worker.notify_job_grab_about_task_end.reset_mock()
        self.worker.vmm.release_vm.reset_mock()
        self.worker.do_job.side_effect = IOError()
        self.worker.run_cycle()

        assert self.worker.notify_job_grab_about_task_end.call_args[1]["do_reschedule"]
        assert self.worker.vmm.release_vm.called
