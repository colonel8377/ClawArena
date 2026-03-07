import contextvars
import uuid

_trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="")


def set_trace_id(trace_id: str) -> None:
    _trace_id_var.set(trace_id)


def get_trace_id() -> str:
    return _trace_id_var.get()


def ensure_trace_id() -> str:
    trace_id = get_trace_id()
    if not trace_id:
        trace_id = uuid.uuid4().hex
        set_trace_id(trace_id)
    return trace_id
