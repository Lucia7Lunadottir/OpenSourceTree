from PyQt6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem, QStyle
from PyQt6.QtGui import QPainter, QPainterPath, QColor, QPen, QBrush, QFont
from PyQt6.QtCore import Qt, QRect, QPoint, QModelIndex

from app.constants import LANE_COLORS, GraphRole, CommitRole, REF_LOCAL_COLOR, REF_REMOTE_COLOR, REF_TAG_COLOR, REF_HEAD_COLOR

LANE_W = 16
NODE_R = 4
ROW_H = 24

BG_NORMAL   = QColor(26, 24, 41)
BG_SELECTED = QColor(100, 50, 140)


def _ref_color(ref: str) -> QColor:
    ref_lower = ref.lower()
    if ref_lower.startswith("head"):
        return REF_HEAD_COLOR
    elif "tag" in ref_lower:
        return REF_TAG_COLOR
    elif "/" in ref:
        return REF_REMOTE_COLOR
    else:
        return REF_LOCAL_COLOR


class CommitGraphDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        if index.column() != 0:
            super().paint(painter, option, index)
            return

        painter.save()

        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        painter.fillRect(option.rect, BG_SELECTED if selected else BG_NORMAL)

        lane_data = index.data(GraphRole)
        commit = index.data(CommitRole)

        if lane_data is None or commit is None:
            painter.restore()
            return

        rect = option.rect
        cx = rect.left()
        cy = rect.top() + rect.height() // 2

        def lane_x(lane: int) -> int:
            return cx + lane * LANE_W + LANE_W // 2

        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Pass-through vertical lines for non-node lanes
        for lane in lane_data.active_lanes:
            if lane == lane_data.node_lane:
                continue
            color = LANE_COLORS[lane % len(LANE_COLORS)]
            painter.setPen(QPen(color, 2))
            lx = lane_x(lane)
            painter.drawLine(lx, rect.top(), lx, rect.bottom())

        # Connections in (from above to this node)
        for from_lane, to_lane in lane_data.connections_in:
            color = LANE_COLORS[from_lane % len(LANE_COLORS)]
            painter.setPen(QPen(color, 2))
            fx, tx = lane_x(from_lane), lane_x(to_lane)
            path = QPainterPath()
            path.moveTo(fx, rect.top())
            path.cubicTo(fx, cy, tx, rect.top(), tx, cy)
            painter.drawPath(path)

        # Node lane vertical segments
        my_lane = lane_data.node_lane
        color = LANE_COLORS[my_lane % len(LANE_COLORS)]
        painter.setPen(QPen(color, 2))
        lx = lane_x(my_lane)
        if index.row() > 0:
            painter.drawLine(lx, rect.top(), lx, cy)
        if lane_data.connections_out or commit.parents:
            painter.drawLine(lx, cy, lx, rect.bottom())

        # Connections out (from node to below)
        for from_lane, to_lane in lane_data.connections_out:
            color = LANE_COLORS[from_lane % len(LANE_COLORS)]
            painter.setPen(QPen(color, 2))
            fx, tx = lane_x(from_lane), lane_x(to_lane)
            path = QPainterPath()
            path.moveTo(fx, cy)
            path.cubicTo(fx, rect.bottom(), tx, cy, tx, rect.bottom())
            painter.drawPath(path)

        # Node circle
        node_color = LANE_COLORS[my_lane % len(LANE_COLORS)]
        painter.setPen(QPen(node_color.darker(130), 1))
        painter.setBrush(QBrush(node_color))
        painter.drawEllipse(QPoint(lx, cy), NODE_R, NODE_R)

        # Ref badges
        badge_x = lx + NODE_R + 6
        if commit.refs:
            badge_font = QFont(painter.font())
            badge_font.setPointSize(8)
            badge_font.setBold(True)
            painter.setFont(badge_font)
            fm = painter.fontMetrics()
            for ref in commit.refs:
                display = ref[8:] if ref.startswith("HEAD -> ") else ref
                text_w = fm.horizontalAdvance(display) + 8
                badge_rect = QRect(badge_x, cy - 9, text_w, 18)
                bg = _ref_color(ref)
                painter.setBrush(QBrush(bg))
                painter.setPen(QPen(bg.darker(130), 1))
                painter.drawRoundedRect(badge_rect, 3, 3)
                painter.setPen(QPen(QColor("#ffffff"), 1))
                painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, display)
                badge_x += text_w + 4

        painter.restore()

    def sizeHint(self, option, index):
        lane_data = index.data(GraphRole)
        max_lane = max(lane_data.active_lanes, default=0) if lane_data else 0
        return option.rect.size().__class__((max_lane + 2) * LANE_W, ROW_H)
