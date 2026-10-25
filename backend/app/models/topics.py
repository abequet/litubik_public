# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Thematic map of the corpus (roadmap chantier 11): one row per clustering
run. The computation is deterministic from its params, but a run is kept so
the map does not change under the team's feet and so cluster labels (typed
or AI-suggested) have something to attach to."""
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.accounts import utcnow


class CorpusTopicRun(Base):
    __tablename__ = "corpus_topic_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    # unique | ta_included | ft_included
    scope: Mapped[str] = mapped_column(String(20), default="unique")
    # requested k (NULL = chosen by silhouette) and the k actually used
    k_requested: Mapped[int | None] = mapped_column(Integer)
    k: Mapped[int] = mapped_column(Integer, default=0)
    n_docs: Mapped[int] = mapped_column(Integer, default=0)
    silhouette: Mapped[float | None] = mapped_column(Float)
    # tsne | svd — how the 2-D positions were obtained
    projection: Mapped[str] = mapped_column(String(10), default="tsne")
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    # {"points": [{"record_id", "x", "y", "cluster", "status"}],
    #  "clusters": [{"id", "size", "terms": [...], "label", "label_is_ai"}]}
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    # provenance of the AI cluster labels, when they were requested
    label_provider: Mapped[str] = mapped_column(String(30), default="")
    label_model: Mapped[str] = mapped_column(String(100), default="")
    label_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow)
