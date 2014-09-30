import argparse
from collections import defaultdict
import json
from pprint import pprint
from _pytest.capture import capsys
import pytest

import six
import time
import copr
from copr.client.parsers import ProjectListParser, CommonMsgErrorOutParser
from copr.client.responses import CoprResponse
from copr.client.exceptions import CoprConfigException, CoprNoConfException, \
    CoprRequestException, CoprUnknownResponseException, CoprException, \
    CoprBuildException
from copr.client import CoprClient
import copr_cli
from copr_cli.main import no_config_warning


if six.PY3:
    from unittest import mock
    from unittest.mock import MagicMock
else:
    import mock
    from mock import MagicMock


import logging

logging.basicConfig(
    level=logging.INFO,
    format= '[%(asctime)s] {%(pathname)s:%(lineno)d} %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)

log = logging.getLogger()
log.info("Logger initiated")


from copr_cli import main


@mock.patch('copr_cli.main.CoprClient')
def test_error_keyboard_interrupt(mock_cc, capsys):


    mock_client = MagicMock(no_config=False)
    mock_client.get_build_details.side_effect =  KeyboardInterrupt()
    mock_cc.create_from_file_config.return_value = mock_client

    with pytest.raises(SystemExit) as err:
        main.main(argv=["status", "123"])

    assert err.value.code == 1
    stdout, stderr = capsys.readouterr()
    assert "Interrupted by user" in stderr


@mock.patch('copr_cli.main.CoprClient')
def test_error_copr_request(mock_cc, capsys):
    error_msg = "error message"

    mock_client = MagicMock(no_config=False)
    mock_client.get_build_details.side_effect = CoprRequestException(error_msg)
    mock_cc.create_from_file_config.return_value = mock_client

    with pytest.raises(SystemExit) as err:
        main.main(argv=["status", "123"])

    assert err.value.code == 1
    stdout, stderr = capsys.readouterr()
    assert "Something went wrong" in stderr
    assert error_msg in stderr

@mock.patch('copr_cli.main.setup_parser')
@mock.patch('copr_cli.main.CoprClient')
def test_error_argument_error(mock_cc, mock_setup_parser, capsys):
    error_msg = "error message"

    mock_client = MagicMock(no_config=False)
    mock_cc.create_from_file_config.return_value = mock_client

    mock_setup_parser.return_value.parse_args.side_effect = \
        argparse.ArgumentTypeError(error_msg)

    with pytest.raises(SystemExit) as err:
         main.main(argv=["status", "123"])

    assert err.value.code == 2
    stdout, stderr = capsys.readouterr()
    assert error_msg in stderr

@mock.patch('copr_cli.main.CoprClient')
def test_error_no_args(mock_cc, capsys):
    mock_client = MagicMock(no_config=False)
    mock_cc.create_from_file_config.return_value = mock_client

    for func_name in ["status", "build", "delete", "create"]:
        with pytest.raises(SystemExit) as err:
            main.main(argv=[func_name])

        assert err.value.code == 2

        stdout, stderr = capsys.readouterr()
        assert "usage: copr-cli" in stderr
        assert "too few arguments" in stderr

@mock.patch('copr_cli.main.CoprClient')
def test_error_copr_common_exception(mock_cc, capsys):
    error_msg = "error message"

    mock_client = MagicMock(no_config=False)
    mock_client.get_build_details.side_effect = \
        CoprException(error_msg)
    mock_cc.create_from_file_config.return_value = mock_client

    with pytest.raises(SystemExit) as err:
        main.main(argv=["status", "123"])

    assert err.value.code == 3
    stdout, stderr = capsys.readouterr()
    assert error_msg in stderr


@mock.patch('copr_cli.main.CoprClient')
def test_error_copr_build_exception(mock_cc, capsys):
    error_msg = "error message"

    mock_client = MagicMock(no_config=False)
    mock_client.create_new_build.side_effect = \
        CoprBuildException(error_msg)
    mock_cc.create_from_file_config.return_value = mock_client

    with pytest.raises(SystemExit) as err:
        main.main(argv=["build", "prj1", "src1"])

    assert err.value.code == 4
    stdout, stderr = capsys.readouterr()
    assert error_msg in stderr


@mock.patch('copr_cli.main.CoprClient')
def test_error_copr_unknown_response(mock_cc, capsys):
    error_msg = "error message"

    mock_client = MagicMock(no_config=False)
    mock_client.get_build_details.side_effect = \
        CoprUnknownResponseException(error_msg)
    mock_cc.create_from_file_config.return_value = mock_client

    with pytest.raises(SystemExit) as err:
        main.main(argv=["status", "123"])

    assert err.value.code == 5
    stdout, stderr = capsys.readouterr()
    assert error_msg in stderr


@mock.patch('copr_cli.main.CoprClient')
def test_cancel_build_no_config(mock_cc, capsys):
    mock_cc.create_from_file_config.side_effect = CoprNoConfException()

    with pytest.raises(SystemExit) as err:
        main.main(argv=["cancel", "123400"])

    assert err.value.code == 6
    out, err = capsys.readouterr()
    assert ("Error: Operation requires api authentication\n"
            "File `~/.config/copr` is missing or incorrect\n") in out

    expected_warning = no_config_warning
    assert expected_warning in out


@mock.patch('copr_cli.main.CoprClient')
def test_cancel_build_response(mock_cc, capsys):
    response_status = "foobar"

    mock_client = MagicMock(no_config=False,)
    mock_client.cancel_build.return_value = MagicMock(status=response_status)
    mock_cc.create_from_file_config.return_value = mock_client

    main.main(argv=["cancel", "123"])
    out, err = capsys.readouterr()
    assert "{}\n".format(response_status) in out



@mock.patch('copr_cli.main.CoprClient')
def test_list_project(mock_cc,  capsys):
    response_data = {"output": "ok",
    "repos": [
      {u'additional_repos': u'http://copr-be.cloud.fedoraproject.org/results/rhscl/httpd24/epel-6-$basearch/ http://copr-be.cloud.fedoraproject.org/results/msuchy/scl-utils/epel-6-$basearch/ http://people.redhat.com/~msuchy/rhscl-1.1-rhel-6-candidate-perl516/',
   u'description': u'A recent stable release of Perl with a number of additional utilities, scripts, and database connectors for MySQL and PostgreSQL. This version provides a large number of new features and enhancements, including new debugging options, improved Unicode support, and better performance.',
   u'instructions': u'',
   u'name': u'perl516',
   u'yum_repos': {u'epel-6-x86_64': u'http://copr-be.cloud.fedoraproject.org/results/rhscl/perl516/epel-6-x86_64/'}},
  {u'additional_repos': u'http://copr-be.cloud.fedoraproject.org/results/msuchy/scl-utils/epel-6-$basearch/ http://copr-be.cloud.fedoraproject.org/results/rhscl/httpd24/epel-6-$basearch/ http://copr-be.cloud.fedoraproject.org/results/rhscl/v8314/epel-6-$basearch/',
   u'description': u'A recent stable release of Ruby with Rails 3.2.8 and a large collection of Ruby gems. This Software Collection gives developers on Red Hat Enterprise Linux 6 access to Ruby 1.9, which provides a number of new features and enhancements, including improved Unicode support, enhanced threading, and faster load times.',
   u'instructions': u'',
   u'name': u'ruby193',
   u'yum_repos': {u'epel-6-x86_64': u'http://copr-be.cloud.fedoraproject.org/results/rhscl/ruby193/epel-6-x86_64/'}}]}

    expected_output = """Name: perl516
  Description: A recent stable release of Perl with a number of additional utilities, scripts, and database connectors for MySQL and PostgreSQL. This version provides a large number of new features and enhancements, including new debugging options, improved Unicode support, and better performance.
  Yum repo(s):
    epel-6-x86_64: http://copr-be.cloud.fedoraproject.org/results/rhscl/perl516/epel-6-x86_64/
  Additional repo: http://copr-be.cloud.fedoraproject.org/results/rhscl/httpd24/epel-6-$basearch/ http://copr-be.cloud.fedoraproject.org/results/msuchy/scl-utils/epel-6-$basearch/ http://people.redhat.com/~msuchy/rhscl-1.1-rhel-6-candidate-perl516/

Name: ruby193
  Description: A recent stable release of Ruby with Rails 3.2.8 and a large collection of Ruby gems. This Software Collection gives developers on Red Hat Enterprise Linux 6 access to Ruby 1.9, which provides a number of new features and enhancements, including improved Unicode support, enhanced threading, and faster load times.
  Yum repo(s):
    epel-6-x86_64: http://copr-be.cloud.fedoraproject.org/results/rhscl/ruby193/epel-6-x86_64/
  Additional repo: http://copr-be.cloud.fedoraproject.org/results/msuchy/scl-utils/epel-6-$basearch/ http://copr-be.cloud.fedoraproject.org/results/rhscl/httpd24/epel-6-$basearch/ http://copr-be.cloud.fedoraproject.org/results/rhscl/v8314/epel-6-$basearch/
"""
    e2 = """Name: perl516
  Description: A recent stable release of Perl with a number of additional utilities, scripts, and database connectors for MySQL and PostgreSQL. This version provides a large number of new features and enhancements, including new debugging options, improved Unicode support, and better performance.
  Yum repo(s):
    epel-6-x86_64: http://copr-be.cloud.fedoraproject.org/results/rhscl/perl516/epel-6-x86_64/
  Additional repo: http://copr-be.cloud.fedoraproject.org/results/rhscl/httpd24/epel-6-$basearch/ http://copr-be.cloud.fedoraproject.org/results/msuchy/scl-utils/epel-6-$basearch/ http://people.redhat.com/~msuchy/rhscl-1.1-rhel-6-candidate-perl516/

Name: ruby193
  Description: A recent stable release of Ruby with Rails 3.2.8 and a large collection of Ruby gems. This Software Collection gives developers on Red Hat Enterprise Linux 6 access to Ruby 1.9, which provides a number of new features and enhancements, including improved Unicode support, enhanced threading, and faster load times.
"""

    # no config
    mock_cc.create_from_file_config.side_effect = CoprNoConfException()
    mocked_client = MagicMock(CoprClient(dict(no_config=True)))

    control_response = CoprResponse(client=None, method="", data=response_data,
                                    parsers=[ProjectListParser, CommonMsgErrorOutParser])
    mocked_client.get_projects_list.return_value = control_response
    mock_cc.return_value = mocked_client

    main.main(argv=["list", "rhscl"])

    out, err = capsys.readouterr()
    assert expected_output in out

    expected_warning = no_config_warning
    assert expected_warning in out


@mock.patch('copr_cli.main.CoprClient')
def test_list_project_no_username(mock_cc,  capsys):
    mock_cc.create_from_file_config.side_effect = CoprNoConfException()

    with pytest.raises(SystemExit) as err:
        main.main(argv=["list"])

    assert err.value.code == 6
    out, err = capsys.readouterr()
    assert "Pass username to command or create `~/.config/copr`" in out


@mock.patch('copr_cli.main.CoprClient')
def test_list_project_no_username2(mock_cc,  capsys):
    mock_cc.create_from_file_config.return_value = CoprClient(defaultdict())

    with pytest.raises(SystemExit) as err:
        main.main(argv=["list"])

    assert err.value.code == 6
    out, err = capsys.readouterr()
    assert "Pass username to command or add it to `~/.config/copr`" in out


@mock.patch('copr_cli.main.CoprClient')
def test_list_project_error_msg(mock_cc,  capsys):
    mock_client = MagicMock(no_config=False, username="dummy")
    mock_cc.create_from_file_config.return_value = mock_client

    mock_response = MagicMock(CoprResponse(None, None, None),
                              output="notok", error="error_msg",
                              projects_list=[])

    mock_client.get_projects_list.return_value = mock_response
    main.main(argv=["list", "projectname"])

    out, err = capsys.readouterr()
    assert "error_msg" in out
    assert "No copr retrieved for user: dummy"


@mock.patch('copr_cli.main.CoprClient')
def test_list_project_empty_list(mock_cc,  capsys):
    mock_client = MagicMock(no_config=False, username="dummy")
    mock_cc.create_from_file_config.return_value = mock_client

    mock_response = MagicMock(CoprResponse(None, None, None),
                              output="ok", projects_list=[])

    mock_client.get_projects_list.return_value = mock_response
    main.main(argv=["list", "projectname"])

    out, err = capsys.readouterr()
    assert "error" not in out
    assert "No copr retrieved for user: dummy"


@mock.patch('copr_cli.main.CoprClient')
def test_status_response(mock_cc, capsys):
    response_status = "foobar"

    mock_client = MagicMock(no_config=False)
    mock_client.get_build_details.return_value = \
        MagicMock(status=response_status)
    mock_cc.create_from_file_config.return_value = mock_client

    main.main(argv=["status", "123"])
    out, err = capsys.readouterr()
    assert "{}\n".format(response_status) in out


@mock.patch('copr_cli.main.CoprClient')
def test_status_response_no_args(mock_cc, capsys):
    mock_client = MagicMock(no_config=False)
    mock_cc.create_from_file_config.return_value = mock_client

    with pytest.raises(SystemExit) as err:
        main.main(argv=["status"])

    assert err.value.code == 2

    stdout, stderr = capsys.readouterr()
    assert "usage: copr-cli" in stderr
    assert "too few arguments" in stderr


@mock.patch('copr_cli.main.CoprClient')
def test_delete_project(mock_cc, capsys):
    response_message = "foobar"

    mock_client = MagicMock(no_config=False)
    mock_client.delete_project.return_value = \
        MagicMock(message=response_message)
    mock_cc.create_from_file_config.return_value = mock_client

    main.main(argv=["delete", "foo"])
    out, err = capsys.readouterr()
    assert "{}\n".format(response_message) in out


@mock.patch('copr_cli.main.CoprClient')
def test_create_project(mock_cc, capsys):
    response_message = "foobar"

    mock_client = MagicMock(no_config=False)
    mock_client.create_project.return_value = \
        MagicMock(message=response_message)
    mock_cc.create_from_file_config.return_value = mock_client

    main.main(argv=[
        "create", "foo",
        "--chroot", "f20", "--chroot", "f21",
        "--description", "desc string",
        "--instructions", "instruction string",
        "--repo", "repo1", "--repo", "repo2",
        "--initial-pkgs", "pkg1"
    ])

    out, err = capsys.readouterr()

    mock_client.create_project.assert_called_with(
        projectname="foo", description="desc string",
        instructions="instruction string", chroots=["f20", "f21"],
        repos=["repo1", "repo2"], initial_pkgs=["pkg1"])

    assert "{}\n".format(response_message) in out
