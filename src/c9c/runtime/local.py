"""Local Implementation"""

import concurrent.futures
import copy
import logging
import sys
import threading
import time
import warnings
from collections import deque

from ..machine import C9Machine, Runtime, State, NoMoreFrames, Future

# https://docs.python.org/3/library/logging.html#logging.basicConfig
LOGGER = logging.getLogger()
logging.basicConfig()


class LocalState(State):
    def __init__(self, *values):
        self._bindings = {}  # ........ current bindings
        self._bs = deque()  # ......... binding stack
        self._ds = deque(values)  # ... data stack
        self._es = deque()  # ......... execution stack
        self.ip = 0
        self.stopped = False

    def set_bind(self, ptr, value):
        self._bindings[ptr] = value

    def get_bind(self, ptr):
        return self._bindings[ptr]

    def ds_push(self, val):
        self._ds.append(val)

    def ds_pop(self):
        return self._ds.pop()

    def ds_peek(self, offset):
        """Peek at the Nth value from the top of the stack (0-indexed)"""
        return self._ds[-(offset + 1)]

    def ds_set(self, offset, value):
        """Set the value at offset in the stack"""
        self._ds[-(offset + 1)] = value

    def es_enter(self, new_ip):
        self._es.append(self.ip)
        self.ip = new_ip
        self._bs.append(self._bindings)
        self._bindings = {}

    def es_return(self):
        if not self._es:
            raise NoMoreFrames
        self.ip = self._es.pop()
        self._bindings = self._bs.pop()

    def show(self):
        print(self.to_table())

    def to_table(self):
        return (
            "Bind: "
            + ", ".join(f"{k}->{v}" for k, v in self._bindings.items())
            + f"\nData: {self._ds}"
            + f"\nEval: {self._es}"
        )


class LocalProbe:
    """A monitoring probe that stops the VM after a number of steps"""

    def __init__(self, *, name="P", max_steps=300):
        self._max_steps = max_steps
        self._step = 0
        self._name = name
        self.logs = []
        self.early_stop = False

    def log(self, text):
        self.logs.append(f"*** <{self._name}> {text}")

    def step_cb(self, m):
        self._step += 1
        self.log(f"[step={self._step}, ip={m.state.ip}] {m.instruction}")
        self.logs.append("Data: " + str(tuple(m.state._ds)))
        if self._step >= self._max_steps:
            self.log(f"MAX STEPS ({self._max_steps}) REACHED!! ***")
            self.early_stop = True
            m._stopped = True

    def on_stopped(self, m):
        kind = "Terminated" if m.terminated else "Stopped"
        self.logs.append(f"*** <{self._name}> {kind} after {self._step} steps. ***")
        self.logs.append(m.state.to_table())

    def print_logs(self):
        print("\n".join(self.logs))


class LocalFuture(Future):
    """A chainable future"""

    def __init__(self):
        self.resolved = False
        self.value = None
        self.chain = None
        self.lock = threading.Lock()
        self.continuations = []

    def add_callback(self, cb):
        self.callbacks.append(cb)

    def add_continuation(self, machine, offset):
        self.continuations.append((machine, offset))

    def resolve(self, value):
        # value: Either LocalFuture or not
        if isinstance(value, LocalFuture):
            if value.resolved:
                self._do_resolve(value.value)
            else:
                value.chain = self
        else:
            self._do_resolve(value)
        return self.resolved

    def _do_resolve(self, value):
        self.resolved = True
        self.value = value
        if self.chain:
            self.chain.resolve(value)
        for machine, offset in self.continuations:
            machine.probe.log(f"{self} resolved, continuing {machine}")
            machine.state.ds_set(offset, value)
            machine.state.stopped = False
            machine.runtime.run_machine(machine)

    def __repr__(self):
        return f"<LocalFuture {id(self)} {self.resolved} ({self.value})>"


class LocalRuntime:
    """Execute and manage machines running locally using the threading module"""

    def __init__(self, executable, do_probe=True):
        self.exception = None
        self.finished = False
        self.result = None
        self._machine_future = {}
        self._do_probe = do_probe
        self._executable = executable
        self._to_join = deque()
        self._top_level = None
        threading.excepthook = self._threading_excepthook

    @property
    def machines(self):
        return self._machine_future.keys()

    @property
    def probes(self):
        return [m.probe for m in self.machines]

    def _new_probe(self):
        if self._do_probe:
            # FIXME probe_cls should handle count
            return LocalProbe(name=f"P{len(self.probes)+1}")
        else:
            return None

    def _new_machine(self, state, entrypoint_fn=None):
        future = LocalFuture()
        probe = self._new_probe()
        machine = C9Machine(self._executable, state, self, probe=probe)
        self._machine_future[machine] = future
        return machine, future

    def _threading_excepthook(self, args):
        self.exception = args

    def run_machine(self, m):
        if m not in self._machine_future:
            raise Exception("Starting a machine before its future exists")
        thread = threading.Thread(target=m.run)
        thread.start()

    def start_first_machine(self, args):
        state = LocalState(*args)
        m, f = self._new_machine(state)
        self._top_level = m
        m.probe.log(f"Top Level {m} => {f}")
        self.run_machine(m)

    def make_fork(self, fn_name, args):
        """Make a machine fork - starting from the given fn_name"""
        state = LocalState(*args)
        state.ip = self._executable.locations[fn_name]
        return self._new_machine(state)

    def on_stopped(self, m):
        pass

    def on_finished(self, result):
        """Top level machine returned a result"""
        self.result = result
        self.finished = True

    def get_future(self, m):
        return self._machine_future[m]

    def is_top_level(self, m):
        return m == self._top_level

    def is_future(self, item):
        return isinstance(item, LocalFuture)


def run(executable, *args, do_probe=True, sleep_interval=0.01):
    runtime = LocalRuntime(executable, do_probe=do_probe)
    runtime.start_first_machine(args)

    while not runtime.finished:
        time.sleep(sleep_interval)

        for m in runtime.machines:
            if m.probe.early_stop:
                raise Exception(f"{m} early stop")

        if runtime.exception:
            raise Exception("A thread died") from runtime.exception.exc_value

    if not all(m.stopped for m in runtime.machines):
        raise Exception("Terminated, but not all machines stopped!")

    return runtime
