"""Тела запросов фронта (camelCase) и тексты ошибок валидации — для предпринимателя, по-русски."""
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel, field_validator
from pydantic_core import PydanticCustomError

from app.responses import ApiError

# Текст, если поле не пришло или пришло не того типа. Свои проверки бросают ru_error с точным текстом.
FIELD_MESSAGES = {
    "email": "Укажите email",
    "password": "Укажите пароль",
    "companyId": "Укажите код компании",
    "companyName": "Укажите название компании",
    "companyInn": "Укажите ИНН компании",
    "legalForm": "Укажите форму: ООО или ИП",
    "industry": "Укажите вид деятельности",
    "operationId": "Укажите номер операции",
    "date": "Укажите дату в формате ГГГГ-ММ-ДД",
    "amount": "Укажите сумму, например 12345.67",
    "direction": "Укажите направление: Поступление или Списание",
    "counterpartyInn": "ИНН контрагента — 10 или 12 цифр",
    "counterpartyName": "Укажите контрагента",
    "paymentPurpose": "Назначение платежа должно быть текстом",
    "asOf": "Укажите дату прогноза в формате ГГГГ-ММ-ДД",
    "horizonDays": "Горизонт — целое число дней от 7 до 90",
    "threshold": "Порог должен быть числом",
    "events": "Список платежей передан в неверном формате",
    "scenario": "Сценарий передан в неверном формате",
    "trace": "Флаг trace должен быть true или false",
    "kind": "Неизвестный тип объяснения",
    "forecast": "Нужен прогноз",
    "base": "Базовый прогноз передан в неверном формате",
    "question": "Вопрос должен быть текстом",
    "version": "Укажите версию модели",
    "lookbackDays": "Период сверки — целое число дней от 1 до 60",
    "dateFrom": "Укажите дату начала в формате ГГГГ-ММ-ДД",
    "dateTo": "Укажите дату окончания в формате ГГГГ-ММ-ДД",
    "marketplace": "Выберите маркетплейс",
    "page": "Номер страницы должен быть числом",
    "size": "Размер страницы должен быть числом",
    "file": "Выберите файл для загрузки",
}
DEFAULT_MESSAGE = "Проверьте значение поля"

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^\W\d_]{2,}$")
INN_RE = re.compile(r"^(\d{10}|\d{12})$")
MAX_AMOUNT = Decimal("10000000000000")


def ru_error(message: str) -> PydanticCustomError:
    return PydanticCustomError("ru", message)


def required_text(value: Any, message: str, max_len: int, too_long: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ru_error(message)
    value = value.strip()
    if len(value) > max_len:
        raise ru_error(too_long)
    return value


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ru_error("Поле должно быть текстом")
    return value.strip() or None


def parse_amount(value: Any) -> Decimal:
    """Сумма > 0, не больше двух знаков после точки. Используется и в CSV-импорте."""
    try:
        amount = Decimal(str(value).strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        raise ru_error("Сумма не распознана, нужен формат 12345.67") from None
    if not amount.is_finite():
        raise ru_error("Сумма не распознана, нужен формат 12345.67")
    if amount <= 0:
        raise ru_error("Сумма должна быть больше нуля")
    if amount.as_tuple().exponent < -2:
        raise ru_error("В сумме больше двух знаков после точки")
    if amount >= MAX_AMOUNT:
        raise ru_error("Сумма слишком большая")
    return amount


class Credentials(BaseModel):
    email: str
    password: str


class RegisterRequest(Credentials):
    @field_validator("email", mode="before")
    @classmethod
    def check_email(cls, v: Any) -> str:
        v = required_text(v, "Укажите email", 255, "Email слишком длинный")
        if not EMAIL_RE.match(v):
            raise ru_error("Проверьте email, похоже, в нём опечатка")
        return v

    @field_validator("password", mode="before")
    @classmethod
    def check_password(cls, v: Any) -> str:
        if not isinstance(v, str) or not v:
            raise ru_error("Придумайте пароль")
        if not 8 <= len(v) <= 72:
            raise ru_error("Пароль должен быть от 8 до 72 символов")
        if len(v.encode("utf-8")) > 72:
            # bcrypt учитывает только первые 72 байта; кириллица — 2 байта на букву
            raise ru_error("Пароль слишком длинный: сократите его или используйте латиницу")
        return v


class LoginRequest(Credentials):
    @field_validator("email", mode="before")
    @classmethod
    def check_email(cls, v: Any) -> str:
        return required_text(v, "Укажите email", 255, "Email слишком длинный")

    @field_validator("password", mode="before")
    @classmethod
    def check_password(cls, v: Any) -> str:
        if not isinstance(v, str) or not v:
            raise ru_error("Укажите пароль")
        return v


class CompanyRequest(BaseModel):
    companyId: str
    companyName: str
    companyInn: str
    legalForm: str
    industry: str

    @field_validator("companyId", mode="before")
    @classmethod
    def check_id(cls, v: Any) -> str:
        return required_text(v, "Укажите код компании", 10, "Код компании — не больше 10 символов")

    @field_validator("companyName", mode="before")
    @classmethod
    def check_name(cls, v: Any) -> str:
        return required_text(v, "Укажите название компании", 255, "Название слишком длинное")

    @field_validator("companyInn", mode="before")
    @classmethod
    def check_inn(cls, v: Any) -> str:
        # Только строка: число потеряло бы ведущие нули
        if not isinstance(v, str) or not v.strip():
            raise ru_error("Укажите ИНН компании")
        v = v.strip()
        if not INN_RE.match(v):
            raise ru_error("ИНН — 10 цифр для ООО или 12 для ИП")
        return v

    @field_validator("legalForm", mode="before")
    @classmethod
    def check_form(cls, v: Any) -> str:
        return required_text(v, "Укажите форму: ООО или ИП", 10, "Форма должна быть ООО или ИП")

    @field_validator("industry", mode="before")
    @classmethod
    def check_industry(cls, v: Any) -> str:
        return required_text(v, "Укажите вид деятельности", 100, "Вид деятельности — не больше 100 символов")


class OperationRequest(BaseModel):
    companyId: str
    operationId: str
    date: date
    amount: Decimal
    direction: str
    counterpartyInn: str | None = None
    counterpartyName: str
    paymentPurpose: str | None = None

    @field_validator("companyId", mode="before")
    @classmethod
    def check_company(cls, v: Any) -> str:
        return required_text(v, "Укажите код компании", 10, "Код компании — не больше 10 символов")

    @field_validator("operationId", mode="before")
    @classmethod
    def check_operation(cls, v: Any) -> str:
        return required_text(v, "Укажите номер операции", 20, "Номер операции — не больше 20 символов")

    @field_validator("amount", mode="before")
    @classmethod
    def check_amount(cls, v: Any) -> Decimal:
        if v is None or isinstance(v, bool) or (isinstance(v, str) and not v.strip()):
            raise ru_error("Укажите сумму")
        return parse_amount(v)

    @field_validator("direction", mode="before")
    @classmethod
    def check_direction(cls, v: Any) -> str:
        v = required_text(v, "Укажите направление: Поступление или Списание", 50,
                          "Направление должно быть «Поступление» или «Списание»")
        if v not in ("Поступление", "Списание"):
            raise ru_error("Направление должно быть «Поступление» или «Списание»")
        return v

    @field_validator("counterpartyInn", mode="before")
    @classmethod
    def check_inn(cls, v: Any) -> str | None:
        v = optional_text(v)
        if v is not None and not INN_RE.match(v):
            raise ru_error("ИНН контрагента — 10 или 12 цифр")
        return v

    @field_validator("counterpartyName", mode="before")
    @classmethod
    def check_name(cls, v: Any) -> str:
        return required_text(v, "Укажите контрагента", 255, "Название контрагента слишком длинное")

    @field_validator("paymentPurpose", mode="before")
    @classmethod
    def check_purpose(cls, v: Any) -> str | None:
        v = optional_text(v)
        if v is not None and len(v) > 2000:
            raise ru_error("Назначение платежа слишком длинное")
        return v


class ForecastRequest(BaseModel):
    asOf: date
    horizonDays: int = 30
    threshold: float = 0
    events: list[dict[str, Any]] = []
    scenario: dict[str, Any] | None = None
    trace: bool = False  # шаги расчёта для вкладки «Как посчитано»

    @field_validator("horizonDays", mode="before")
    @classmethod
    def default_horizon(cls, v: Any) -> Any:
        return 30 if v is None else v

    @field_validator("horizonDays")
    @classmethod
    def check_horizon(cls, v: int) -> int:
        # ML-шлюз принимает 7..90 (service/schemas.py)
        if not 7 <= v <= 90:
            raise ru_error("Горизонт прогноза — от 7 до 90 дней")
        return v

    @field_validator("threshold", mode="before")
    @classmethod
    def default_threshold(cls, v: Any) -> Any:
        return 0 if v is None else v

    @field_validator("threshold")
    @classmethod
    def check_threshold(cls, v: float) -> float:
        if v < 0:
            raise ru_error("Порог не может быть отрицательным")
        return v

    @field_validator("events", mode="before")
    @classmethod
    def default_events(cls, v: Any) -> Any:
        return [] if v is None else v


class ExplainRequest(BaseModel):
    kind: str
    forecast: dict[str, Any]
    base: dict[str, Any] | None = None
    question: str | None = None

    @field_validator("kind")
    @classmethod
    def check_kind(cls, v: str) -> str:
        if v not in ("summary", "gap", "scenario", "answer"):
            raise ru_error("Неизвестный тип объяснения")
        return v

    @field_validator("question")
    @classmethod
    def check_question(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        if len(v.strip()) > 300:
            raise ru_error("Вопрос — не длиннее 300 символов")
        return v.strip()


class ActivateRequest(BaseModel):
    version: str

    @field_validator("version", mode="before")
    @classmethod
    def check_version(cls, v: Any) -> str:
        return required_text(v, "Укажите версию модели", 64, "Слишком длинное имя версии")


class RetrainRequest(BaseModel):
    version: str | None = None
    events: str | None = None


class MarketplaceConnectRequest(BaseModel):
    companyId: str
    marketplace: str
    clientId: str | None = None     # OZON
    apiKey: str | None = None       # OZON
    token: str | None = None        # Wildberries, Яндекс Маркет
    businessId: str | None = None   # Яндекс Маркет: идентификатор кабинета

    @field_validator("companyId", mode="before")
    @classmethod
    def check_company(cls, v: Any) -> str:
        return required_text(v, "Выберите компанию", 10, "Код компании — не больше 10 символов")

    @field_validator("marketplace")
    @classmethod
    def check_marketplace(cls, v: str) -> str:
        if v not in ("ozon", "wb", "yandex"):
            raise ru_error("Выберите маркетплейс: OZON, Wildberries или Яндекс Маркет")
        return v

    @field_validator("clientId", "apiKey", "token", "businessId", mode="before")
    @classmethod
    def strip_secret(cls, v: Any) -> str | None:
        v = optional_text(v)
        if v is not None and len(v) > 500:
            raise ru_error("Слишком длинное значение")
        return v

    def credentials(self) -> dict:
        """Ключи для выбранного маркетплейса; не хватает поля → ru-ошибка с именем поля."""
        need = {"ozon": [("clientId", "client_id", "Укажите Client-Id"), ("apiKey", "api_key", "Укажите Api-Key")],
                "wb": [("token", "token", "Укажите токен Wildberries")],
                "yandex": [("token", "token", "Укажите токен Яндекс Маркета"),
                           ("businessId", "business_id", "Укажите идентификатор кабинета (businessId)")]}
        result = {}
        for field, key, message in need[self.marketplace]:
            value = getattr(self, field)
            if not value:
                raise ApiError(400, message, field)
            result[key] = value
        return result


class MarketplaceSyncRequest(BaseModel):
    dateFrom: date
    dateTo: date
    asOf: date | None = None   # дата начала расчёта категорий, как при загрузке выписки

    @field_validator("dateTo")
    @classmethod
    def check_period(cls, v: date, info) -> date:
        start = info.data.get("dateFrom")
        if start and v < start:
            raise ru_error("Дата окончания раньше даты начала")
        if start and (v - start).days > 731:
            raise ru_error("Период — не больше двух лет")
        return v
