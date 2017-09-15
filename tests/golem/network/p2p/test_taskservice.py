import unittest
import tempfile
from unittest.mock import patch, Mock, ANY
from devp2p.peer import Peer
from golem.utils import decode_hex
from golem.network.p2p.taskservice import TaskRequestRejection, TaskRejection, \
    ResultRejection

from golem.model import Payment

def override_ip_info(*_, **__):
    from golem.network.stun.pystun import OpenInternet
    return OpenInternet, '1.2.3.4', 40102


def create_client(datadir):
    # executed in a subprocess
    from golem.network.stun import pystun
    pystun.get_ip_info = override_ip_info

    from golem.client import Client
    client = Client(datadir=datadir,
                    use_monitor=False,
                    transaction_system=False,
                    connect_to_known_hosts=False,
                    use_docker_machine_manager=False,
                    estimated_lux_performance=1000.0,
                    estimated_blender_performance=1000.0)

    client.services['task_service'].setup(task_server=Mock())
    return client


def create_proto():
    proto = Mock()
    proto.receive_reject_callbacks = []
    proto.receive_task_request_callbacks = []
    proto.receive_task_callbacks = []
    proto.receive_failure_callbacks = []
    proto.receive_result_callbacks = []
    proto.receive_accept_result_callbacks = []
    proto.receive_payment_request_callbacks = []
    proto.receive_payment_callbacks = []

    return proto


class TestGolemService(unittest.TestCase):

    def setUp(self):
        Peer.dumb_remote_timeout = 0.1
        datadir = tempfile.mkdtemp(prefix='golem_service_1')
        self.client = create_client(datadir)

    def tearDown(self):
        self.client.quit()

    @patch('gevent._socket2.socket')
    def test_get_session(self, socket):
        pubkey = "f325434534fdfd"
        gservice = self.client.services['task_service']
        peer = Peer(self.client.services['peermanager'], socket)
        peer.remote_pubkey = decode_hex("f325434534fdfd")
        peer.connect_service(gservice)
        self.client.services['peermanager'].peers.append(peer)
        result = gservice.get_session(pubkey)
        assert result
        peer.stop()

    @patch('gevent.event.AsyncResult')
    @patch('golem.network.p2p.taskservice.TaskService.get_session')
    def test_connect(self, get_session, AsyncResult):
        addresses = ['10.10.10.1', '10.10.10.2', '10.10.10.3']
        pubkey = "f325434534fdfd"
        gservice = self.client.services['task_service']
        gservice.peer_manager.connect = Mock()
        gservice.peer_manager.connect.return_value = True
        get_session.return_value = None
        result_pos = gservice.connect(pubkey, addresses)
        assert not result_pos.exception
        gservice.peer_manager.connect.return_value = False
        gservice.peer_manager.errors.add(addresses[0], 'connection timeout')
        gservice.peer_manager.errors.add(addresses[1], 'connection timeout')
        gservice.peer_manager.errors.add(addresses[2], 'connection timeout')
        gservice._connecting = []
        result_neg = gservice.connect(pubkey, addresses)
        assert result_neg.exception

    @patch('golem.network.p2p.taskservice.TaskService.connect')
    def test_spawn_connect(self, connect):
        gservice = self.client.services['task_service']
        addresses = ['10.10.10.1', '10.10.10.2', '10.10.10.3']
        pubkey = "f325434534fdfd"
        success = Mock()
        error = Mock()
        gservice.spawn_connect(pubkey, addresses, success, error)
        import gevent
        gevent.get_hub().join()
        assert success.called
        connect.side_effect = Exception()
        gservice.spawn_connect(pubkey, addresses, success, error)
        gevent.get_hub().join()
        assert error.called


    def test_wire_proto_start(self):
        gservice = self.client.services['task_service']
        gservice.wire_protocol = object

        proto = create_proto()

        gservice.on_wire_protocol_start(proto)

        self.assertGreater(len(proto.receive_reject_callbacks), 0)
        self.assertGreater(len(proto.receive_task_request_callbacks), 0)
        self.assertGreater(len(proto.receive_task_callbacks), 0)
        self.assertGreater(len(proto.receive_failure_callbacks), 0)
        self.assertGreater(len(proto.receive_result_callbacks), 0)
        self.assertGreater(len(proto.receive_accept_result_callbacks), 0)
        self.assertGreater(len(proto.receive_payment_request_callbacks), 0)
        self.assertGreater(len(proto.receive_payment_callbacks), 0)

    def test_send_task_request(self):
        gservice = self.client.services['task_service']
        proto = create_proto()
        task_id = '1234'
        performance = 'great'
        price = 'afordable'
        max_disk = 'unlimited'
        max_memory = 'unlimited'
        max_cpus = 'unlimited'
        proto.send_task_request = Mock()
        proto.peer.ip_port = ['10.10.10.1', 0]
        gservice.send_task_request(proto, task_id, performance, price, max_disk,
            max_memory, max_cpus)
        assert proto.send_task_request.called

    @patch('golem.network.p2p.peermanager.GolemPeerManager.disconnect')
    @patch('gevent._socket2.socket')
    def test_receive_task_request(self, socket, disconnect):
        gservice = self.client.services['task_service']
        proto = create_proto()
        task_id = '1234'
        performance = 'great'
        price = 'afordable'
        max_disk = 'unlimited'
        max_memory = 'unlimited'
        max_cpus = 'unlimited'

        proto.peer.ip_port = ['10.10.10.1', 0]
        proto.peer.connection.getpeername = Mock()
        proto.peer.connection.getpeername.return_value = ['10.10.10.1', 0]

        gservice.task_manager.get_next_subtask = Mock(return_value=(Mock(),
            False, False))
        gservice.send_task = Mock()
        gservice.receive_task_request(proto, task_id, performance, price, max_disk,
                                   max_memory, max_cpus)
        assert gservice.send_task.called

        gservice.task_manager.get_next_subtask.return_value = (None,
            True, False)
        gservice.send_reject_task_request = Mock()
        gservice.receive_task_request(proto, task_id, performance, price, max_disk,
                                   max_memory, max_cpus)
        assert gservice.send_reject_task_request.called
        gservice.send_reject_task_request.assert_called_once_with(proto, task_id,
            TaskRequestRejection.TASK_ID_UNKNOWN)

        gservice.task_manager.get_next_subtask.return_value = (None,
            False, True)
        gservice.receive_task_request(proto, task_id, performance, price, max_disk,
                                   max_memory, max_cpus)
        assert gservice.send_reject_task_request.called
        gservice.send_reject_task_request.assert_called_with(proto, task_id,
            TaskRequestRejection.DOWNLOADING_RESULT)

        gservice.task_manager.get_next_subtask.return_value = (None,
            False, False)
        gservice.receive_task_request(proto, task_id, performance, price, max_disk,
                                   max_memory, max_cpus)
        assert gservice.send_reject_task_request.called
        gservice.send_reject_task_request.assert_called_with(proto, task_id,
            TaskRequestRejection.NO_MORE_SUBTASKS)

    def test_send_reject_task_request(self):
        gservice = self.client.services['task_service']
        proto = create_proto()
        task_id = '1234'
        proto.send_reject = Mock()
        proto.peer.ip_port = ['10.10.10.1', 0]
        for reason in TaskRequestRejection.__dict__:
            gservice.send_reject_task_request(proto, task_id, reason)
            proto.send_reject.assert_called_with(1, reason, task_id)

    def test_receive_reject_task_request(self):
        gservice = self.client.services['task_service']
        proto = create_proto()
        task_id = '1234'
        gservice.task_computer.task_request_rejected = Mock()
        gservice.task_server.remove_task_header = Mock()
        gservice.task_computer.session_closed = Mock()
        for reason in TaskRequestRejection.__dict__:
            gservice._receive_reject_task_request(proto, reason, task_id)
            if reason == TaskRequestRejection.DOWNLOADING_RESULT:
                assert not gservice.task_computer.task_request_rejected.called
                assert not gservice.task_server.remove_task_header.called
                assert not gservice.task_computer.session_closed.called
            else:
                gservice.task_computer.task_request_rejected.assert_called_with(
                    task_id, reason)
                gservice.task_server.remove_task_header.assert_called_with(
                    task_id)
                assert gservice.task_computer.session_closed.called


    def test_send_task(self):
        gservice = self.client.services['task_service']
        ctd = Mock()
        proto = create_proto()
        proto.send_task = Mock()
        proto.peer.ip_port = ['10.10.10.1', 0]
        self.client.resource_server = Mock()
        self.client.resource_server.resource_manager.build_client_options\
            = Mock(return_value=Mock())
        self.client.resource_server.resource_manager.get_resources = \
            Mock(return_value=Mock())
        gservice.task_server.client = self.client
        gservice.task_server.keys_auth.public_key = "f325434534fdfd"
        gservice.send_task(proto, ctd)
        assert proto.send_task.called

    def test_receive_task(self):
        gservice = self.client.services['task_service']
        proto = create_proto()
        proto.peer.ip_port = ['10.10.10.1', 0]
        proto.peer.remote_pubkey = "f325434534fdfd"
        gservice.task_manager = Mock()
        gservice._validate_ctd = Mock()
        gservice._set_ctd_env_params = Mock()
        gservice.task_manager.comp_task_keeper.receive_subtask = Mock(
            return_value=True)
        gservice.task_server.add_task_session = Mock()
        gservice.task_computer.task_given = Mock()
        gservice.task_server.client = self.client
        gservice.task_server.client.resource_server = Mock()
        resources_from_wire = Mock()
        gservice.task_server.client.resource_server.resource_manager.from_wire\
            = Mock(return_value=resources_from_wire)
        gservice.task_server.pull_resources = Mock()
        definition = Mock()
        definition.task_id = "1234"
        resources = Mock()
        resource_options = Mock()
        gservice.receive_task(proto, definition, resources, resource_options)
        gservice.task_server.pull_resources.assert_called_with(
            definition.task_id, resources_from_wire,
            client_options=resource_options)

    def test_send_reject_task(self):
        gservice = self.client.services['task_service']
        proto = create_proto()
        task_id = '1234'
        proto.send_reject = Mock()
        proto.peer.ip_port = ['10.10.10.1', 0]
        for reason in TaskRejection.__dict__:
            gservice.send_reject_task(proto, task_id, reason)
            proto.send_reject.assert_called_with(2, reason, task_id)

    def test_receive_reject_task(self):
        gservice = self.client.services['task_service']
        proto = create_proto()
        subtask_task_id = '1234'
        proto.peer.ip_port = ['10.10.10.1', 0]
        proto.peer.remote_pubkey = "f325434534fdfd"
        gservice.task_manager.get_node_id_for_subtask = Mock(
            return_value="f325434534fdfd")
        gservice.task_manager.task_computation_failure = Mock()
        for reason in TaskRejection.__dict__:
            gservice._receive_reject_task(proto, reason, subtask_task_id)
            msg = 'Subtask computation rejected: {}'.format(reason)
            gservice.task_manager.task_computation_failure.assert_called_with(
                subtask_task_id, msg)

    def test_send_result(self):
        gservice = self.client.services['task_service']
        proto = create_proto()
        proto.send_result = Mock()
        proto.peer.ip_port = ['10.10.10.1', 0]

        subtask_id = "1234"
        computation_time = "10"
        resource_hash = "ABCDEF12345"
        resource_secret = "secret"
        resource_options = Mock()
        eth_account = "0xABCDEF12345"

        gservice.send_result(proto, subtask_id, computation_time, resource_hash,
            resource_secret, resource_options, eth_account)
        assert proto.send_result.called

    def test_receive_result(self):
        gservice = self.client.services['task_service']
        proto = create_proto()
        proto.peer.ip_port = ['10.10.10.1', 0]

        subtask_id = "1234"
        task_id = "5678"
        computation_time = "10"
        resource_hash = "ABCDEF12345"
        resource_secret = "secret"
        resource_options = Mock()
        eth_account = "0xABCDEF12345"

        gservice._set_eth_account = Mock()
        gservice.task_manager.task_result_incoming = Mock()
        gservice.task_manager.task_result_manager.pull_package = Mock()
        task = Mock()
        gservice.task_manager.subtask2task_mapping = {subtask_id : task_id }

        gservice.task_manager.tasks = {task_id: None}
        gservice.send_reject_result = Mock()
        gservice.receive_result(proto, subtask_id, computation_time, resource_hash,
            resource_secret, resource_options, eth_account)
        gservice.send_reject_result.assert_called_with(proto, subtask_id,
            ResultRejection.SUBTASK_ID_UNKNOWN)
        assert not gservice.task_manager.task_result_manager.pull_package.called

        gservice.task_manager.tasks[task_id] = task
        gservice.receive_result(proto, subtask_id, computation_time, resource_hash,
            resource_secret, resource_options, eth_account)
        gservice.task_manager.task_result_manager.pull_package.\
            assert_called_with(resource_hash, task_id, subtask_id,
                resource_secret, success=ANY, error=ANY,
                    client_options=resource_options, output_dir=ANY)

    @patch('golem.model.Payment.subtask')
    @patch('golem.model.Payment.get')
    def test_receive_payment_request(self, get, subtask):
        gservice = self.client.services['task_service']
        proto = create_proto()
        proto.peer.ip_port = ['10.10.10.1', 0]

        subtask_id = "1234"
        payment = Mock()
        subtask = subtask_id
        gservice.send_payment = Mock()

        get.side_effect = Payment.DoesNotExist
        gservice.receive_payment_request(proto, subtask_id)
        assert not gservice.send_payment.called

        get.side_effect = None
        get.return_value = payment
        gservice.receive_payment_request(proto, subtask_id)
        gservice.send_payment.assert_called_with(proto, payment)

    def test_receive_payment(self):
        gservice = self.client.services['task_service']
        proto = create_proto()
        proto.peer.ip_port = ['10.10.10.1', 0]

        subtask_id = "1234"
        transaction_id = "5678"
        remuneration = "2"

        block_number = None
        gservice.receive_payment(proto, subtask_id, transaction_id,
                                 remuneration, block_number)
        assert not gservice.task_server.reward_for_subtask_paid.called

        block_number = "15"
        transaction_id = None
        gservice.receive_payment(proto, subtask_id, transaction_id,
                                 remuneration, block_number)
        assert not gservice.task_server.reward_for_subtask_paid.called

        block_number = "15"
        transaction_id = "5678"
        gservice.task_server.reward_for_subtask_paid = Mock()
        gservice.receive_payment(proto, subtask_id, transaction_id,
            remuneration, block_number)
        gservice.task_server.reward_for_subtask_paid.assert_called_with(
            subtask_id=subtask_id, reward=remuneration,
            transaction_id=transaction_id, block_number=block_number)
