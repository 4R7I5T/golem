import copy
import decimal
import os
import logging
import yaml
import queue

from ethereum.utils import denoms
from typing import List, Optional

import golem_messages
from golem_messages import idgenerator
from golem_verificator.verifier import SubtaskVerificationState

from apps.core.task.coretaskstate import TaskDefinition, Options
from apps.golemcc.golemccenvironment import GolemccTaskEnvironment
from golem.network.p2p.node import Node
from golem.resource.dirmanager import DirManager
from golem.core.common import timeout_to_deadline, string_to_timeout,\
                              to_unicode, get_golem_path
from golem.docker.environment import DockerEnvironment
from golem.task.taskbase import Task, ResultType, TaskState, TaskBuilder, \
                                TaskTypeInfo, TaskDefaults, TaskHeader, \
                                AcceptClientVerdict
from golem.task.taskclient import TaskClient

logger = logging.getLogger(__name__)

def apply(obj, *initial_data, **kwargs):
    for dictionary in initial_data:
        for key in dictionary:
            setattr(obj, key, dictionary[key])
    for key in kwargs:
        setattr(obj, key, kwargs[key])


class GolemccTaskDefinition(TaskDefinition):
    def __init__(self):
        super().__init__()
        self.task_type = 'Golemcc'


class GolemccTaskTypeInfo(TaskTypeInfo):
    def __init__(self):
        super().__init__(
            "Golemcc",
            GolemccTaskDefinition,
            TaskDefaults(),
            Options,
            GolemccTaskBuilder
        )


class BasicTaskBuilder(TaskBuilder):
    def __init__(self,
                 owner: Node,
                 task_definition: TaskDefinition,
                 dir_manager: DirManager) -> None:
        super().__init__()
        self.task_definition = task_definition
        self.root_path = dir_manager.root_path
        self.dir_manager = dir_manager
        self.owner = owner
        self.src_code = ""

    @classmethod
    def build_definition(cls, task_type: TaskTypeInfo, dictionary,
                         minimal=False):
        """ Build task defintion from dictionary with described options.
        :param dict dictionary: described all options need to build a task
        :param bool minimal: if this option is set too True, then only minimal
        definition that can be used for task testing can be build. Otherwise
        all necessary options must be specified in dictionary
        """
        td = task_type.definition()
        apply(td, dictionary)
        td.timeout = string_to_timeout(dictionary['timeout'])
        td.subtask_timeout = string_to_timeout(dictionary['subtask_timeout'])
        td.max_price = \
            int(decimal.Decimal(dictionary['bid']) * denoms.ether)
        return td


class GolemccTaskBuilder(BasicTaskBuilder):
    def build(self) -> 'Task':
        return GolemccTask(self.owner,
                             self.task_definition,
                             self.dir_manager)


class GolemccBenchmarkTaskBuilder(GolemccTaskBuilder):
    def build(self) -> 'Task':
        self.task_definition.files = '/home/mplebanski/main.c;'
        self.task_definitions.stdargs = '-o main main.c'
        self.task_definitions.env = ''
        return GolemccTask(self.owner,
                             self.task_definition,
                             self.dir_manager)


class DockerTask(Task):
    ENVIRONMENT_CLASS=DockerEnvironment

    def __init__(self,
                 owner: Node,
                 task_definition: TaskDefinition,
                 dir_manager: DirManager) -> None:

        self.environment = self.ENVIRONMENT_CLASS()

        if task_definition.docker_images:
            self.docker_images = task_definition.docker_images
        elif isinstance(self.environment, DockerEnvironment):
            self.docker_images = self.environment.docker_images
        else:
            self.docker_images = None

        th = TaskHeader(
            task_id=task_definition.task_id,
            environment=self.environment.get_id(),
            task_owner=owner,
            deadline=timeout_to_deadline(task_definition.timeout),
            subtask_timeout=task_definition.subtask_timeout,
            subtasks_count=task_definition.subtasks_count,
            resource_size=1024,
            estimated_memory=task_definition.estimated_memory,
            max_price=task_definition.max_price,
            concent_enabled=task_definition.concent_enabled,
        )
        with open(self.environment.main_program_file, 'r') as script_file:
            src_code = script_file.read()
        super().__init__(th, src_code, task_definition)


class ExtraDataBuilder(object):
    def __init__(self, header, subtask_id, subtask_data,
                    src_code, short_desc, performance, docker_images=None):
        self.header = header
        self.subtask_id = subtask_id
        self.subtask_data = subtask_data
        self.src_code = src_code
        self.short_desc = short_desc
        self.performance = performance
        self.docker_images = docker_images

    def get_result(self):
        ctd = golem_messages.message.ComputeTaskDef()
        ctd['task_id'] = self.header.task_id
        ctd['subtask_id'] = self.subtask_id
        ctd['extra_data'] = self.subtask_data
        ctd['short_description'] = self.short_desc
        ctd['src_code'] = self.src_code
        ctd['performance'] = self.performance
        if self.docker_images:
            ctd['docker_images'] = [di.to_dict() for di in self.docker_images]
        ctd['deadline'] = min(timeout_to_deadline(self.header.subtask_timeout),
                            self.header.deadline)
        return Task.ExtraData(ctd=ctd)


class GolemccTask(DockerTask):
    ENVIRONMENT_CLASS = GolemccTaskEnvironment

    def __init__(self,
                 owner: Node,
                 task_definition: TaskDefinition,
                 dir_manager: DirManager)
        super().__init__(owner, task_definition, dir_manager)
        self.dispatched_subtasks = {}
        self.progress = 0.0

    def initialize(self, dir_manager):
        """Called after adding a new task, may initialize or create some resources
        or do other required operations.
        :param DirManager dir_manager: DirManager instance for accessing temp dir for this task
        """
        pass

    def create_subtask_id(self) -> str:
        return idgenerator.generate_new_id_from_id(self.header.task_id)

    def query_extra_data(self, perf_index: float, num_cores: int = 1,
                         node_id: Optional[str] = None,
                         node_name: Optional[str] = None) -> 'ExtraData':
        """ Called when a node asks with given parameters asks for a new
        subtask to compute.
        :param perf_index: performance that given node declares
        :param num_cores: number of cores that current node declares
        :param node_id: id of a node that wants to get a next subtask
        :param node_name: name of a node that wants to get a next subtask
        """
        subtask_id = self.create_subtask_id()
        subtask_data = {}

        self.dispatched_subtasks[subtask_id] = {'extra_data': subtask_data}

        subtask_builder = ExtraDataBuilder(self.header, subtask_id, subtask_data,
                                           self.src_code,
                                           self.short_extra_data_repr(subtask_data),
                                           perf_index, self.docker_images)
        return subtask_builder.get_result()

    def query_extra_data_for_test_task(self) -> golem_messages.message.ComputeTaskDef:  # noqa pylint:disable=line-too-long
        pass

    def short_extra_data_repr(self, extra_data: Task.ExtraData) -> str:
        """ Should return a short string with general task description that may be used for logging or stats gathering.
        :param extra_data
        :return str:
        """
        return 'golemcc task'

    def needs_computation(self) -> bool:
        """ Return information if there are still some subtasks that may be dispended
        :return bool: True if there are still subtask that should be computed, False otherwise
        """
        # return self.work_queue
        pass

    def finished_computation(self) -> bool:
        """ Return information if tasks has been fully computed
        :return bool: True if there is all tasks has been computed and verified
        """
        # return not self.work_queue and not self.dispatched_subtasks
        pass

    def computation_finished(self, subtask_id, task_result,
                             result_type=ResultType.DATA,
                             verification_finished=None):
        """ Inform about finished subtask
        :param subtask_id: finished subtask id
        :param task_result: task result, can be binary data or list of files
        :param result_type: ResultType representation
        """
        del self.dispatched_subtasks[subtask_id]
        if self.finished_computation():
            self.progress = 1.0
        try:
            if verification_finished:
                verification_finished()
        except Exception as e:
            logger.exception("")

    def computation_failed(self, subtask_id):
        """ Inform that computation of a task with given id has failed
        :param subtask_id:
        """
        raise RuntimeError("Computation failed")

    def verify_subtask(self, subtask_id):
        """ Verify given subtask
        :param subtask_id:
        :return bool: True if a subtask passed verification, False otherwise
        """
        return True

    def verify_task(self):
        """ Verify whole task after computation
        :return bool: True if task passed verification, False otherwise
        """
        return self.finished_computation()

    def get_total_tasks(self) -> int:
        """ Return total number of tasks that should be computed
        :return int: number should be greater than 0
        """
        # It won't
        return 1

    def get_active_tasks(self) -> int:
        """ Return number of tasks that are currently being computed
        :return int: number should be between 0 and a result of get_total_tasks
        """
        return len(self.dispatched_subtasks)

    def get_tasks_left(self) -> int:
        """ Return number of tasks that still should be computed
        :return int: number should be between 0 and a result of get_total_tasks
        """
        # TODO analogical to get_total_tasks
        return 0 if self.dispatched_subtasks else 1

    def restart(self):
        """ Restart all subtask computation for this task """
        # Restart workflow
        raise NotImplementedError()

    def restart_subtask(self, subtask_id):
        """ Restart subtask with given id """
        # Restart specific fw_id
        raise NotImplementedError()

    def abort(self):
        """ Abort task and all computations """
        # Possibly delete the workflow and see what happens on provider side
        raise NotImplementedError()

    def get_progress(self) -> float:
        """ Return task computations progress
        :return float: Return number between 0.0 and 1.0.
        """
        return self.progress

    def get_resources(self) -> list:
        """ Return list of files that are need to compute this task."""
        # TODO but what for?
        return self.task_definition.resources

    def update_task_state(self, task_state: TaskState):
        """Update some task information taking into account new state.
        :param TaskState task_state:
        """
        # TODO
        return  # Implement in derived class

    def get_trust_mod(self, subtask_id) -> int:
        """ Return trust modifier for given subtask. This number may be taken into account during increasing
        or decreasing trust for given node after successful or failed computation.
        :param subtask_id:
        :return int:
        """
        return 1.0

    def add_resources(self, resources: set):
        """ Add resources to a task
        :param resources:
        """
        raise NotImplementedError()

    def copy_subtask_results(
            self, subtask_id: int, old_subtask_info: dict, results: List[str]) \
            -> None:
        """
        Copy results of a single subtask from another task
        """
        raise NotImplementedError()

    def should_accept_client(self, node_id):
        if self.needs_computation():
            return AcceptClientVerdict.ACCEPTED
        elif self.finished_computation():
            return AcceptClientVerdict.ACCEPTED
        else:
            return AcceptClientVerdict.SHOULD_WAIT

    def get_stdout(self, subtask_id) -> str:
        """ Return stdout received after computation of subtask_id, if there is no data available
        return empty string
        :param subtask_id:
        :return str:
        """
        # That should be something acquired in computation_finished?
        return ""

    def get_stderr(self, subtask_id) -> str:
        """ Return stderr received after computation of subtask_id, if there is no data available
        return emtpy string
        :param subtask_id:
        :return str:
        """
        # That should be something acquired in computation_finished?
        return ""

    def get_results(self, subtask_id) -> List:
        """ Return list of files containing results for subtask with given id
        :param subtask_id:
        :return list:
        """
        return []

    def result_incoming(self, subtask_id):
        """ Informs that a computed task result is being retrieved
        :param subtask_id:
        :return:
        """
        pass

    def get_output_names(self) -> List:
        """ Return list of files containing final import task results
        :return list:
        """
        # Called only on enqueue by taskmanager to fill tasks_states
        return []

    def get_output_states(self) -> List:
        """ Return list of states of final task results
        :return list:
        """
        import pdb; pdb.set_trace()
        return []

    def to_dictionary(self):
        return {
            'id': to_unicode(self.header.task_id),
            'name': to_unicode(self.task_definition.name),
            'type': to_unicode(self.task_definition.task_type),
            'subtasks_count': self.get_total_tasks(),
            'progress': self.get_progress()
        }

    def accept_client(self, node_id):
        verdict = self.should_accept_client(node_id)

        if verdict == AcceptClientVerdict.ACCEPTED:
            client = TaskClient(node_id)
            client.start()
        return verdict
