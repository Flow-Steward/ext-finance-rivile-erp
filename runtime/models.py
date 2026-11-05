"""Immutable description of one Rivile ERP Public API endpoint."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Endpoint:
    """One documented Rivile ERP endpoint and the inputs its operation accepts.

    ``path_params`` and ``query_params`` pair each operation input name with the
    exact wire name (``("delivery_id", "deliveryId")``). ``query_params`` also
    carries the value kind (``text``, ``integer``, ``number``, ``boolean``).
    List endpoints (``paged``) take ``page``/``size``/``filter``; the filter may
    only name the fields Rivile documents for that list (``filter_fields``).
    """

    operation_id: str
    http_method: str
    path: str
    write: bool
    paged: bool
    has_body: bool
    body_required: bool
    binary: bool
    path_params: tuple[tuple[str, str], ...]
    query_params: tuple[tuple[str, str, str], ...]
    filter_fields: tuple[str, ...]
    #: Where the answer goes: ``list`` (records of a page), ``file`` (a workflow
    #: file), ``record`` (an object), ``records`` (an array) or ``value`` (a scalar).
    payload: str
    title: str
    group: str

    @property
    def wire(self) -> str:
        """The endpoint as written in the Rivile ERP OpenAPI document."""
        return f"{self.http_method} {self.path}"


__all__ = ["Endpoint"]
