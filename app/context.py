from contextvars import ContextVar

# X-Request-ID текущего запроса: попадает в логи и пробрасывается в ML и LLM
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
