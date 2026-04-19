import os
import random
import sys
import sqlite3
import math
from typing import Dict, List, Optional, Set

from PyQt5.QtCore import QPropertyAnimation, QEasingCurve, QPointF, QVariant  # type: ignore
from PyQt5.QtGui import QColor  # type: ignore
from PyQt5.QtWidgets import (  # type: ignore
    QApplication,
    QCheckBox,
    QCompleter,
    QDockWidget,
    QHBoxLayout,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from qgis.PyQt.QtCore import Qt  # type: ignore
from qgis.core import (  # type: ignore
    QgsApplication,
    QgsCategorizedSymbolRenderer,
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsLayerTreeModel,
    QgsLineSymbol,
    QgsMarkerSymbol,
    QgsPointXY,
    QgsProject,
    QgsRectangle,
    QgsRendererCategory,
    QgsVectorLayer,
    QgsWkbTypes,
    QgsPalLayerSettings,
    QgsTextBufferSettings,
    QgsTextFormat,
    QgsVectorLayerSimpleLabeling,
    Qgis
)
from qgis.gui import (  # type: ignore
    QgsLayerTreeMapCanvasBridge,
    QgsLayerTreeView,
    QgsMapCanvas,
    QgsMapToolIdentifyFeature,
)

from storage import DialectStorage
from questions_dock import QuestionsDock
from answers_dock import AnswersDock
from settlement_info_dock import SettlementInfoDock


class MainWindow(QMainWindow):
    FIXED_SEARCH_SCALE = 50000
    ZOOM_ANIMATION_DURATION_MS = 450

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Диалектологический атлас")
        self.resize(1280, 760)

        self.current_question_id: Optional[int] = None
        self.current_settlement_id: Optional[int] = None
        self.current_settlement_name: Optional[str] = None
        self.answers_map_layer: Optional[QgsVectorLayer] = None
        self.isogloss_layer: Optional[QgsVectorLayer] = None
        self._pan_animation: Optional[QPropertyAnimation] = None
        self.multivalue_marker_layer: Optional[QgsVectorLayer] = None

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        self.search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Найти населённый пункт")
        self.search_button = QPushButton("Найти")
        self.isogloss_checkbox = QCheckBox("Изоглоссы")
        self.hide_multivalue_checkbox = QCheckBox("Скрыть многозначные пункты")

        self.search_layout.addWidget(self.search_input)
        self.search_layout.addWidget(self.search_button)
        self.search_layout.addWidget(self.isogloss_checkbox)
        self.search_layout.addWidget(self.hide_multivalue_checkbox)
        layout.addLayout(self.search_layout)

        self.canvas = QgsMapCanvas()
        layout.addWidget(self.canvas)
        self.canvas.extentsChanged.connect(self.on_canvas_extent_changed)

        self.project = QgsProject.instance()
        self.bridge = QgsLayerTreeMapCanvasBridge(
            self.project.layerTreeRoot(),
            self.canvas
        )

        self.project.read("dia2.qgz")

        self.storage = DialectStorage(
            gpkg_path="dial_data.gpkg",
            project=self.project
        )

        self.setup_layers_panel()
        self.setup_questions_panel()
        self.setup_answers_panel()
        self.setup_settlement_info_panel()
        self.setup_search()
        self.setup_settlement_pick_tool()

        if self.storage.exists():
            self.storage.add_service_layer_to_project()
            self.refresh_search_completer()

        self.load_questions()

        self.canvas.zoomToFullExtent()
        self.canvas.refresh()

    def setup_layers_panel(self) -> None:
        self.layer_tree_view = QgsLayerTreeView()
        self.layer_tree_model = QgsLayerTreeModel(self.project.layerTreeRoot())
        self.layer_tree_model.setFlags(
            QgsLayerTreeModel.AllowNodeChangeVisibility
            | QgsLayerTreeModel.ShowLegend
        )
        self.layer_tree_view.setModel(self.layer_tree_model)

        self.layers_dock = QDockWidget("Слои", self)
        self.layers_dock.setWidget(self.layer_tree_view)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.layers_dock)

    def setup_questions_panel(self) -> None:
        self.questions_dock = QuestionsDock(self)
        self.questions_dock.add_requested.connect(self.add_question)
        self.questions_dock.delete_requested.connect(self.delete_selected_question)
        self.questions_dock.selection_changed.connect(self.on_question_selection_changed)
        self.addDockWidget(Qt.RightDockWidgetArea, self.questions_dock)

    def setup_answers_panel(self) -> None:
        self.answers_dock = AnswersDock(self)
        self.answers_dock.add_requested.connect(self.add_answer)
        self.answers_dock.delete_requested.connect(self.delete_selected_answer)
        self.addDockWidget(Qt.RightDockWidgetArea, self.answers_dock)

    def setup_settlement_info_panel(self) -> None:
        self.settlement_info_dock = SettlementInfoDock(self)
        self.addDockWidget(Qt.RightDockWidgetArea, self.settlement_info_dock)

    def setup_search(self) -> None:
        self.refresh_search_completer()
        self.search_button.clicked.connect(self.search_settlement)
        self.search_input.returnPressed.connect(self.search_settlement)
        self.isogloss_checkbox.stateChanged.connect(self.on_isogloss_toggled)
        self.hide_multivalue_checkbox.stateChanged.connect(self.on_hide_multivalue_toggled)

    def on_hide_multivalue_toggled(self) -> None:
        self.refresh_map_for_current_question()

    def refresh_search_completer(self) -> None:
        completer = QCompleter(self.storage.get_settlement_names(), self)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        self.search_input.setCompleter(completer)

    def setup_settlement_pick_tool(self) -> None:
        settlements_layer = self.storage.get_settlements_layer()
        if settlements_layer is None:
            self.pick_tool = None
            return

        self.pick_tool = QgsMapToolIdentifyFeature(self.canvas, settlements_layer)
        self.pick_tool.featureIdentified.connect(self.on_settlement_picked)
        self.canvas.setMapTool(self.pick_tool)

    def load_questions(self) -> None:
        self.questions_dock.clear_questions()
        for question_id, text in self.storage.get_questions():
            self.questions_dock.add_question_item(question_id, text)

    def load_answers_for_current_question(self) -> None:
        self.answers_dock.clear_answers()

        if self.current_question_id is None:
            return

        for answer_id, answer_text, settlement_name in self.storage.get_answers_for_question(self.current_question_id):
            self.answers_dock.add_answer_item(answer_id, answer_text, settlement_name)

    def refresh_settlement_info(self) -> None:
        self.settlement_info_dock.clear_items()

        if self.current_settlement_id is None:
            self.settlement_info_dock.set_settlement_name(None)
            return

        self.settlement_info_dock.set_settlement_name(self.current_settlement_name)
        for question_text, answer_text in self.storage.get_settlement_questions(self.current_settlement_id):
            self.settlement_info_dock.add_item(question_text, answer_text)

    def search_settlement(self) -> None:
        name = self.search_input.text().strip()
        if not name:
            return

        feature = self.storage.find_settlement_feature_by_name(name)
        if feature is None:
            QMessageBox.information(
                self,
                "Не найдено",
                "Населённый пункт не найден."
            )
            return

        self.on_settlement_picked(feature)
        self.zoom_to_feature(feature)

    def zoom_to_feature(self, feature: QgsFeature) -> None:
        geom = feature.geometry()
        if geom is None or geom.isEmpty():
            return

        point = geom.asPoint()
        target_center = QgsPointXY(point.x(), point.y())
        self.animate_to_point(target_center, self.FIXED_SEARCH_SCALE)

    def animate_to_point(self, target_center: QgsPointXY, target_scale: float) -> None:
        current_center = self.canvas.center()

        if self._pan_animation is not None:
            self._pan_animation.stop()
            self._pan_animation.deleteLater()
            self._pan_animation = None

        self._pan_animation = QPropertyAnimation(self, b"")
        self._pan_animation.setDuration(self.ZOOM_ANIMATION_DURATION_MS)
        self._pan_animation.setEasingCurve(QEasingCurve.InOutCubic)
        self._pan_animation.setStartValue(QPointF(current_center.x(), current_center.y()))
        self._pan_animation.setEndValue(QPointF(target_center.x(), target_center.y()))

        def on_value_changed(value):
            self.canvas.setCenter(QgsPointXY(value.x(), value.y()))
            self.canvas.refresh()

        def on_finished():
            self.canvas.setCenter(target_center)
            self.canvas.zoomScale(target_scale)
            self.canvas.refresh()

        self._pan_animation.valueChanged.connect(on_value_changed)
        self._pan_animation.finished.connect(on_finished)
        self._pan_animation.start()

    def add_question(self) -> None:
        text = self.questions_dock.get_input_text()
        if not text:
            QMessageBox.information(self, "Пустой ввод", "Введите текст вопроса.")
            return

        try:
            self.storage.add_question(text)

            if self.storage.exists():
                self.storage.add_service_layer_to_project()

            self.refresh_search_completer()
            self.questions_dock.clear_input()
            self.load_questions()

        except sqlite3.IntegrityError:
            QMessageBox.warning(self, "Дубликат", "Такой вопрос уже существует.")
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Ошибка",
                f"Не удалось добавить вопрос:\n{exc}"
            )

    def delete_selected_question(self) -> None:
        question_id = self.questions_dock.current_question_id()
        if question_id is None:
            QMessageBox.information(
                self,
                "Нет выбора",
                "Выберите вопрос в списке."
            )
            return

        reply = QMessageBox.question(
            self,
            "Удаление вопроса",
            "Удалить выбранный вопрос?\nСвязанные ответы также будут удалены.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        try:
            self.storage.delete_question(question_id)
            self.current_question_id = None
            self.load_questions()
            self.answers_dock.clear_answers()
            self.answers_dock.set_current_question(None)
            self.remove_answers_map_layer()
            self.remove_isogloss_layer()
            self.remove_multivalue_marker_layer()
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Ошибка",
                f"Не удалось удалить вопрос:\n{exc}"
            )

    def on_question_selection_changed(self) -> None:
        self.current_question_id = self.questions_dock.current_question_id()
        self.answers_dock.clear_answers()

        current_text = self.questions_dock.current_question_text()
        if current_text is None or self.current_question_id is None:
            self.answers_dock.set_current_question(None)
            self.remove_answers_map_layer()
            self.remove_isogloss_layer()
            self.remove_multivalue_marker_layer()
            return

        self.answers_dock.set_current_question(current_text)
        self.load_answers_for_current_question()
        self.refresh_map_for_current_question()

    def on_settlement_picked(self, feature: QgsFeature) -> None:
        id_field = self.storage.get_settlement_id_field()
        name_field = self.storage.get_settlement_name_field()

        if not id_field or not name_field:
            QMessageBox.warning(
                self,
                "Ошибка",
                "В слое settlements не найдены поля ID/имени."
            )
            return

        try:
            self.current_settlement_id = int(feature[id_field])
            self.current_settlement_name = str(feature[name_field])
            self.answers_dock.set_current_settlement(self.current_settlement_name)
            self.refresh_settlement_info()
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Ошибка выбора",
                f"Не удалось прочитать атрибуты населённого пункта:\n{exc}"
            )

    def on_isogloss_toggled(self) -> None:
        self.refresh_map_for_current_question()

    def add_answer(self) -> None:
        if self.current_question_id is None:
            QMessageBox.information(
                self,
                "Нет вопроса",
                "Сначала выберите вопрос."
            )
            return

        if self.current_settlement_id is None:
            QMessageBox.information(
                self,
                "Нет населённого пункта",
                "Сначала щёлкните по населённому пункту на карте."
            )
            return

        answer_text = self.answers_dock.get_input_text()
        if not answer_text:
            QMessageBox.information(
                self,
                "Пустой ввод",
                "Введите текст ответа."
            )
            return

        try:
            self.storage.add_answer(
                question_id=self.current_question_id,
                settlement_id=self.current_settlement_id,
                answer_text=answer_text,
            )
            self.load_answers_for_current_question()
            self.refresh_map_for_current_question()
            self.refresh_settlement_info()
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Ошибка",
                f"Не удалось добавить ответ:\n{exc}"
            )

    def delete_selected_answer(self) -> None:
        answer_id = self.answers_dock.current_answer_id()
        if answer_id is None:
            QMessageBox.information(
                self,
                "Нет выбора",
                "Выберите ответ в списке."
            )
            return

        reply = QMessageBox.question(
            self,
            "Удаление ответа",
            "Удалить выбранный ответ?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        try:
            self.storage.delete_answer(int(answer_id))
            self.load_answers_for_current_question()
            self.refresh_map_for_current_question()
            self.refresh_settlement_info()
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Ошибка",
                f"Не удалось удалить ответ:\n{exc}"
            )

    def refresh_map_for_current_question(self) -> None:
        if self.current_question_id is None:
            self.remove_answers_map_layer()
            self.remove_isogloss_layer()
            self.remove_multivalue_marker_layer()
            return

        records = self.storage.get_map_data_for_question(self.current_question_id)

        if self.hide_multivalue_checkbox.isChecked():
            records = [
                record for record in records
                if not bool(record.get("is_multivalue", False))
            ]

        if not records:
            self.remove_answers_map_layer()
            self.remove_isogloss_layer()
            self.remove_multivalue_marker_layer()
            return

        settlements_layer = self.storage.get_settlements_layer()
        if settlements_layer is None:
            return

        crs_authid = settlements_layer.crs().authid()
        layer = QgsVectorLayer(
            f"Point?crs={crs_authid}",
            "dialect_answers",
            "memory"
        )

        provider = layer.dataProvider()
        provider.addAttributes([
            QgsField("settlement_id", QVariant.Int),
            QgsField("settlement_name", QVariant.String),
            QgsField("answer_text", QVariant.String),
            QgsField("is_multivalue", QVariant.Bool),
            QgsField("answer_count", QVariant.Int),
        ])
        layer.updateFields()

        features = []
        for record in records:
            point = self.compute_display_point(record)

            feature = QgsFeature(layer.fields())
            feature.setGeometry(QgsGeometry.fromPointXY(point))
            feature["settlement_id"] = record["settlement_id"]
            feature["settlement_name"] = record["settlement_name"]
            feature["answer_text"] = record["answer_text"]
            feature["is_multivalue"] = bool(record["is_multivalue"])
            feature["answer_count"] = int(record["answer_count"])
            features.append(feature)

        provider.addFeatures(features)
        layer.updateExtents()

        self.apply_random_categorized_renderer(layer)

        self.remove_answers_map_layer()
        self.answers_map_layer = layer
        self.project.addMapLayer(self.answers_map_layer)
        self.refresh_multivalue_marker_layer(records)

        isogloss_records = [
            record for record in records
            if not bool(record.get("is_multivalue", False))
        ]
        self.refresh_isoglosses_for_current_question(isogloss_records)

    def compute_display_point(self, record: Dict, offset_px: float = 18.0) -> QgsPointXY:
        x = float(record["x"])
        y = float(record["y"])
        count = int(record.get("answer_count", 1))
        index = int(record.get("answer_index", 0))

        if count <= 1:
            return QgsPointXY(x, y)

        map_units_per_pixel = self.canvas.mapUnitsPerPixel()

        if count == 2:
            dx = (-0.5 if index == 0 else 0.5) * offset_px * 2.5 * map_units_per_pixel
            return QgsPointXY(x + dx, y)

        radius = offset_px * map_units_per_pixel
        angle_step = 2.0 * math.pi / count

        angle = (-math.pi / 2.0) + index * angle_step

        dx = math.cos(angle) * radius
        dy = math.sin(angle) * radius

        return QgsPointXY(x + dx, y + dy)

    def refresh_isoglosses_for_current_question(self, records: Optional[List[dict]] = None) -> None:
        self.remove_isogloss_layer()

        if not self.isogloss_checkbox.isChecked():
            return

        if self.current_question_id is None:
            return

        if records is None:
            records = self.storage.get_map_data_for_question(self.current_question_id)

        clean_records = [
            record for record in records
            if not bool(record.get("is_multivalue", False))
        ]

        if not clean_records or len(clean_records) < 3:
            return

        grouped = self.group_records_by_answer(clean_records)
        if len(grouped) < 2:
            return

        settlements_layer = self.storage.get_settlements_layer()
        if settlements_layer is None:
            return

        crs_authid = settlements_layer.crs().authid()
        layer = QgsVectorLayer(
            f"LineString?crs={crs_authid}",
            "dialect_isoglosses",
            "memory"
        )

        provider = layer.dataProvider()
        provider.addAttributes([
            QgsField("pair_label", QVariant.String),
        ])
        layer.updateFields()

        isogloss_features = self.build_voronoi_isogloss_features(clean_records, layer)
        if not isogloss_features:
            return

        provider.addFeatures(isogloss_features)
        layer.updateExtents()
        self.apply_isogloss_renderer(layer)

        self.isogloss_layer = layer
        self.project.addMapLayer(self.isogloss_layer)

    def build_voronoi_isogloss_features(
        self,
        records: List[dict],
        layer: QgsVectorLayer
    ) -> List[QgsFeature]:
        multipoint = [QgsPointXY(float(r["x"]), float(r["y"])) for r in records]
        mp_geom = QgsGeometry.fromMultiPointXY(multipoint)
        if mp_geom is None or mp_geom.isEmpty():
            return []

        extent_rect = self.compute_voronoi_extent(records)
        extent_geom = QgsGeometry.fromRect(extent_rect)
        voronoi = mp_geom.voronoiDiagram(extent_geom, 0.0, False)
        if voronoi is None or voronoi.isEmpty():
            return []

        cells = self.extract_voronoi_cells(voronoi)
        if not cells:
            return []

        labeled_cells = []
        for cell in cells:
            matched = self.match_cell_to_record(cell, records)
            if matched is None:
                continue
            labeled_cells.append((cell, matched))

        if len(labeled_cells) < 2:
            return []

        seen_boundaries: Set[str] = set()
        features: List[QgsFeature] = []

        for i in range(len(labeled_cells)):
            cell_a, rec_a = labeled_cells[i]
            ans_a = str(rec_a["answer_text"])

            for j in range(i + 1, len(labeled_cells)):
                cell_b, rec_b = labeled_cells[j]
                ans_b = str(rec_b["answer_text"])

                if ans_a == ans_b:
                    continue

                shared = cell_a.intersection(cell_b)
                if shared is None or shared.isEmpty():
                    continue

                line_geoms = self.extract_line_geometries(shared)
                if not line_geoms:
                    continue

                pair_label = " / ".join(sorted([ans_a, ans_b]))
                for line_geom in line_geoms:
                    key = self.geometry_signature(line_geom)
                    if not key or key in seen_boundaries:
                        continue
                    seen_boundaries.add(key)

                    feature = QgsFeature(layer.fields())
                    feature.setGeometry(line_geom)
                    feature["pair_label"] = pair_label
                    features.append(feature)

        return features

    def compute_voronoi_extent(self, records: List[dict]) -> QgsRectangle:
        xs = [float(r["x"]) for r in records]
        ys = [float(r["y"]) for r in records]

        min_x = min(xs)
        max_x = max(xs)
        min_y = min(ys)
        max_y = max(ys)

        width = max(max_x - min_x, 1.0)
        height = max(max_y - min_y, 1.0)
        margin_x = width * 0.25
        margin_y = height * 0.25

        return QgsRectangle(
            min_x - margin_x,
            min_y - margin_y,
            max_x + margin_x,
            max_y + margin_y,
        )

    def extract_voronoi_cells(self, voronoi_geom: QgsGeometry) -> List[QgsGeometry]:
        cells: List[QgsGeometry] = []

        if voronoi_geom.isMultipart():
            for geom in voronoi_geom.asGeometryCollection():
                if geom is not None and not geom.isEmpty():
                    cells.append(geom)
        else:
            cells.append(voronoi_geom)

        return cells

    def match_cell_to_record(self, cell: QgsGeometry, records: List[dict]) -> Optional[dict]:
        for record in records:
            pt = QgsGeometry.fromPointXY(QgsPointXY(float(record["x"]), float(record["y"])))
            try:
                if cell.contains(pt):
                    return record
            except Exception:
                continue

        try:
            centroid = cell.centroid()
            if centroid is None or centroid.isEmpty():
                return None
            cpt = centroid.asPoint()
        except Exception:
            return None

        best = None
        best_dist = None
        for record in records:
            dx = float(record["x"]) - cpt.x()
            dy = float(record["y"]) - cpt.y()
            dist = dx * dx + dy * dy
            if best_dist is None or dist < best_dist:
                best_dist = dist
                best = record

        return best

    def extract_line_geometries(self, geom: QgsGeometry) -> List[QgsGeometry]:
        result: List[QgsGeometry] = []

        if geom is None or geom.isEmpty():
            return result

        geom_type = QgsWkbTypes.geometryType(geom.wkbType())
        if geom_type != QgsWkbTypes.LineGeometry:
            return result

        if geom.isMultipart():
            for line in geom.asMultiPolyline():
                if len(line) >= 2:
                    result.append(QgsGeometry.fromPolylineXY(line))
        else:
            line = geom.asPolyline()
            if len(line) >= 2:
                result.append(QgsGeometry.fromPolylineXY(line))

        return result

    def geometry_signature(self, geom: QgsGeometry) -> str:
        if geom is None or geom.isEmpty():
            return ""

        try:
            bbox = geom.boundingBox()
            return (
                f"{round(bbox.xMinimum(), 6)}|{round(bbox.yMinimum(), 6)}|"
                f"{round(bbox.xMaximum(), 6)}|{round(bbox.yMaximum(), 6)}|"
                f"{round(geom.length(), 6)}"
            )
        except Exception:
            return ""

    def group_records_by_answer(self, records: List[dict]) -> Dict[str, List[dict]]:
        grouped: Dict[str, List[dict]] = {}
        for record in records:
            answer_text = str(record["answer_text"])
            grouped.setdefault(answer_text, []).append(record)
        return grouped

    def remove_answers_map_layer(self) -> None:
        layers_to_remove = []

        for layer in self.project.mapLayers().values():
            if layer.name() == "dialect_answers":
                layers_to_remove.append(layer.id())

        for layer_id in layers_to_remove:
            self.project.removeMapLayer(layer_id)

        self.answers_map_layer = None

    def remove_isogloss_layer(self) -> None:
        layers_to_remove = []

        for layer in self.project.mapLayers().values():
            if layer.name() == "dialect_isoglosses":
                layers_to_remove.append(layer.id())

        for layer_id in layers_to_remove:
            self.project.removeMapLayer(layer_id)

        self.isogloss_layer = None

    def apply_random_categorized_renderer(self, layer: QgsVectorLayer) -> None:
        values = []
        for feature in layer.getFeatures():
            value = str(feature["answer_text"])
            if value not in values:
                values.append(value)

        categories = []
        for value in values:
            symbol = self.create_random_marker_symbol(
                seed_text=f"{self.current_question_id}:{value}"
            )
            categories.append(QgsRendererCategory(value, symbol, value))

        renderer = QgsCategorizedSymbolRenderer("answer_text", categories)
        layer.setRenderer(renderer)
        layer.triggerRepaint()

    def apply_isogloss_renderer(self, layer: QgsVectorLayer) -> None:
        values = []
        for feature in layer.getFeatures():
            value = str(feature["pair_label"])
            if value not in values:
                values.append(value)

        categories = []
        for value in values:
            symbol = self.create_random_line_symbol(
                seed_text=f"{self.current_question_id}:{value}"
            )
            categories.append(QgsRendererCategory(value, symbol, value))

        renderer = QgsCategorizedSymbolRenderer("pair_label", categories)
        layer.setRenderer(renderer)
        layer.triggerRepaint()

    def create_random_marker_symbol(self, seed_text: str) -> QgsMarkerSymbol:
        rng = random.Random(seed_text)

        symbol_names = [
            "square",
            "triangle",
            "diamond",
            "cross",
            "x",
            "pentagon",
            "hexagon",
            "star",
        ]

        symbol_name = rng.choice(symbol_names)
        size = rng.uniform(3.2, 4.6)
        fill_color = self.create_stable_color(seed_text)
        outline_color = QColor(30, 30, 30)

        symbol = QgsMarkerSymbol.createSimple({
            "name": symbol_name,
            "size": str(size),
            "outline_width": "0.4",
            "color": fill_color.name(),
            "outline_color": outline_color.name(),
        })

        return symbol

    def create_random_line_symbol(self, seed_text: str) -> QgsLineSymbol:
        color = self.create_stable_color(seed_text)
        symbol = QgsLineSymbol.createSimple({
            "line_color": color.name(),
            "line_width": "1.2",
            "line_style": "dash",
        })
        return symbol

    def create_stable_color(self, seed_text: str) -> QColor:
        rng = random.Random(seed_text)
        return QColor(
            rng.randint(40, 220),
            rng.randint(40, 220),
            rng.randint(40, 220),
        )
    def remove_multivalue_marker_layer(self) -> None:
        layers_to_remove = []

        for layer in self.project.mapLayers().values():
            if layer.name() == "dialect_multivalue_markers":
                layers_to_remove.append(layer.id())

        for layer_id in layers_to_remove:
            self.project.removeMapLayer(layer_id)

        self.multivalue_marker_layer = None

    def refresh_multivalue_marker_layer(self, records: List[dict]) -> None:
        if self.hide_multivalue_checkbox.isChecked():
            self.remove_multivalue_marker_layer()
            return
        
        self.remove_multivalue_marker_layer()

        multivalue_records = {}
        for record in records:
            if not bool(record.get("is_multivalue", False)):
                continue

            settlement_id = int(record["settlement_id"])
            if settlement_id not in multivalue_records:
                multivalue_records[settlement_id] = {
                    "settlement_id": settlement_id,
                    "settlement_name": str(record["settlement_name"]),
                    "x": float(record["x"]),
                    "y": float(record["y"]),
                    "answer_count": int(record.get("answer_count", 2)),
                }

        if not multivalue_records:
            return

        settlements_layer = self.storage.get_settlements_layer()
        if settlements_layer is None:
            return

        crs_authid = settlements_layer.crs().authid()
        layer = QgsVectorLayer(
            f"Point?crs={crs_authid}",
            "dialect_multivalue_markers",
            "memory"
        )

        provider = layer.dataProvider()
        provider.addAttributes([
            QgsField("settlement_id", QVariant.Int),
            QgsField("settlement_name", QVariant.String),
            QgsField("answer_count", QVariant.Int),
        ])
        layer.updateFields()

        features = []
        for record in multivalue_records.values():
            feature = QgsFeature(layer.fields())
            feature.setGeometry(
                QgsGeometry.fromPointXY(
                    QgsPointXY(record["x"], record["y"])
                )
            )
            feature["settlement_id"] = record["settlement_id"]
            feature["settlement_name"] = record["settlement_name"]
            feature["answer_count"] = record["answer_count"]
            features.append(feature)

        provider.addFeatures(features)
        layer.updateExtents()

        symbol = QgsMarkerSymbol.createSimple({
            "name": "circle",
            "size": "4.2",
            "color": "#ffffff",
            "outline_color": "#000000",
            "outline_width": "0.6",
        })
        layer.renderer().setSymbol(symbol)

        text_format = QgsTextFormat()
        text_format.setSize(5.8)
        text_format.setColor(QColor("#000000"))

        buffer = QgsTextBufferSettings()
        buffer.setEnabled(True)
        buffer.setSize(0.35)
        buffer.setColor(QColor("#ffffff"))
        text_format.setBuffer(buffer)

        label_settings = QgsPalLayerSettings()
        label_settings.enabled = True
        label_settings.fieldName = "answer_count"
        label_settings.setFormat(text_format)

        placement_value = getattr(QgsPalLayerSettings, "OverPoint", None)
        if placement_value is None:
            label_placement_enum = getattr(Qgis, "LabelPlacement", None)
            if label_placement_enum is not None:
                placement_value = getattr(label_placement_enum, "OverPoint", None)
        if placement_value is not None:
            try:
                label_settings.placement = placement_value
            except Exception:
                pass

        quad_over_value = getattr(QgsPalLayerSettings, "QuadrantOver", None)
        if quad_over_value is not None:
            try:
                label_settings.quadOffset = quad_over_value
            except Exception:
                pass

        label_settings.dist = 0

        layer.setLabelsEnabled(True)
        layer.setLabeling(QgsVectorLayerSimpleLabeling(label_settings))
        layer.triggerRepaint()

        self.multivalue_marker_layer = layer
        self.project.addMapLayer(self.multivalue_marker_layer)

    def on_canvas_extent_changed(self) -> None:
        if self.current_question_id is None:
            return

        self.refresh_map_for_current_question()


def detect_qgis_prefix_path() -> str:
    candidates = []

    env_prefixes = [
        os.environ.get("QGIS_PREFIX_PATH"),
        os.environ.get("QGIS_PREFIX"),
    ]
    for value in env_prefixes:
        if value:
            candidates.append(value)

    program_files = [
        os.environ.get("ProgramW6432"),
        os.environ.get("ProgramFiles"),
        os.environ.get("ProgramFiles(x86)"),
    ]

    relative_candidates = [
        r"QGIS 3.40.0",
        r"QGIS 3.38.0",
        r"QGIS 3.36.0",
        r"QGIS 3.34.0",
        r"QGIS 3.32.0",
        r"QGIS 3.28.0",
        r"QGIS",
    ]

    for base in program_files:
        if not base:
            continue

        for rel in relative_candidates:
            candidates.append(os.path.join(base, rel))
            candidates.append(os.path.join(base, rel, "apps", "qgis"))
            candidates.append(os.path.join(base, rel, "apps", "qgis-ltr"))
            candidates.append(os.path.join(base, rel, "apps", "qgis-dev"))

    checked = set()
    for path in candidates:
        if not path:
            continue

        norm = os.path.normpath(path)
        if norm in checked:
            continue
        checked.add(norm)

        if os.path.exists(os.path.join(norm, "apps")):
            return norm

        if os.path.exists(os.path.join(norm, "resources")):
            return norm

        if os.path.exists(os.path.join(norm, "python")):
            return norm

    raise RuntimeError(
        "Не удалось определить путь к QGIS автоматически. "
        "Измените переменную окружения QGIS_PREFIX_PATH в main()."
    )


def main():
    QGIS_PREFIX_PATH = detect_qgis_prefix_path()
    QgsApplication.setPrefixPath(QGIS_PREFIX_PATH, True)

    app = QgsApplication([], True)
    app.initQgis()

    window = MainWindow()
    window.show()

    exit_code = app.exec_()
    app.exitQgis()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()