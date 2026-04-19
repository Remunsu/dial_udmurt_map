import os
import sqlite3
from typing import Dict, List, Optional, Tuple

from qgis.core import (  # type: ignore
    QgsFeature,
    QgsProject,
    QgsVectorFileWriter,
    QgsVectorLayer,
)


class DialectStorage:
    def __init__(
        self,
        gpkg_path: str,
        project: QgsProject,
        service_layer_name: str = "dialect_answers_display",
    ):
        self.gpkg_path = gpkg_path
        self.project = project
        self.service_layer_name = service_layer_name

    def exists(self) -> bool:
        return os.path.exists(self.gpkg_path)

    def ensure_storage_exists(self) -> None:
        if self.exists():
            return

        self._create_empty_gpkg_with_service_layer()
        self._create_sql_tables()
        self._copy_settlements_reference()
        self.add_service_layer_to_project()

    def _create_empty_gpkg_with_service_layer(self) -> None:
        memory_layer = QgsVectorLayer(
            "Point?crs=EPSG:4326&field=id:integer&field=question_id:integer&field=variant:string",
            self.service_layer_name,
            "memory",
        )

        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = self.service_layer_name

        error = QgsVectorFileWriter.writeAsVectorFormatV3(
            memory_layer,
            self.gpkg_path,
            self.project.transformContext(),
            options,
        )
        if error[0] != QgsVectorFileWriter.NoError:
            raise RuntimeError(f"Не удалось создать GeoPackage: {error}")

    def _create_sql_tables(self) -> None:
        with sqlite3.connect(self.gpkg_path) as conn:
            cur = conn.cursor()

            cur.execute("""
                CREATE TABLE IF NOT EXISTS questions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    text TEXT NOT NULL UNIQUE,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS answers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    question_id INTEGER NOT NULL,
                    settlement_id INTEGER NOT NULL,
                    answer_text TEXT NOT NULL,
                    comment TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (question_id) REFERENCES questions(id)
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS settlements_ref (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL
                )
            """)

            conn.commit()

    def _copy_settlements_reference(self) -> None:
        settlements_layer = self.find_layer_by_name("settlements")
        if settlements_layer is None or not settlements_layer.isValid():
            return

        field_names = [field.name() for field in settlements_layer.fields()]

        id_field = self._pick_existing_field(
            field_names,
            ["id", "ID", "fid", "FID", "osm_id", "settlement_id"]
        )
        name_field = self._pick_existing_field(
            field_names,
            ["name", "NAME", "name_ru", "settlement", "locality"]
        )

        if not id_field or not name_field:
            return

        with sqlite3.connect(self.gpkg_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM settlements_ref")
            if cur.fetchone()[0] > 0:
                return

            for feature in settlements_layer.getFeatures():
                settlement_id = feature[id_field]
                settlement_name = feature[name_field]

                if settlement_id is None or settlement_name in (None, ""):
                    continue

                cur.execute("""
                    INSERT OR IGNORE INTO settlements_ref (id, name)
                    VALUES (?, ?)
                """, (int(settlement_id), str(settlement_name)))

            conn.commit()

    def get_questions(self) -> List[Tuple[int, str]]:
        if not self.exists():
            return []

        with sqlite3.connect(self.gpkg_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, text FROM questions ORDER BY id")
            return cur.fetchall()

    def add_question(self, text: str) -> int:
        text = text.strip()
        if not text:
            raise ValueError("Пустой текст вопроса.")

        self.ensure_storage_exists()

        with sqlite3.connect(self.gpkg_path) as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO questions (text) VALUES (?)",
                (text,)
            )
            conn.commit()
            return cur.lastrowid

    def delete_question(self, question_id: int) -> None:
        if not self.exists():
            return

        with sqlite3.connect(self.gpkg_path) as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM answers WHERE question_id = ?", (question_id,))
            cur.execute("DELETE FROM questions WHERE id = ?", (question_id,))
            conn.commit()

    def get_answers_for_question(self, question_id: int) -> List[Tuple[int, str, str]]:
        if not self.exists():
            return []

        with sqlite3.connect(self.gpkg_path) as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT
                    a.id,
                    a.answer_text,
                    COALESCE(s.name, '[без названия]')
                FROM answers a
                LEFT JOIN settlements_ref s ON s.id = a.settlement_id
                WHERE a.question_id = ?
                ORDER BY s.name, a.answer_text
            """, (question_id,))
            return cur.fetchall()

    def add_answer(
        self,
        question_id: int,
        settlement_id: int,
        answer_text: str,
        comment: str = "",
    ) -> int:
        answer_text = answer_text.strip()
        if not answer_text:
            raise ValueError("Пустой текст ответа.")

        self.ensure_storage_exists()

        with sqlite3.connect(self.gpkg_path) as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO answers (question_id, settlement_id, answer_text, comment)
                VALUES (?, ?, ?, ?)
            """, (question_id, settlement_id, answer_text, comment))
            conn.commit()
            return cur.lastrowid

    def delete_answer(self, answer_id: int) -> None:
        if not self.exists():
            return

        with sqlite3.connect(self.gpkg_path) as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM answers WHERE id = ?", (answer_id,))
            conn.commit()

    def get_map_data_for_question(self, question_id: int) -> List[Dict]:
        """
        Возвращает по одной записи на КАЖДЫЙ отображаемый символ.
        Для многозначных пунктов будет несколько записей с одинаковыми x/y.
        """
        if not self.exists():
            return []

        settlements_layer = self.get_settlements_layer()
        if settlements_layer is None:
            return []

        id_field = self.get_settlement_id_field()
        name_field = self.get_settlement_name_field()
        if not id_field or not name_field:
            return []

        answers_by_settlement: Dict[int, List[str]] = {}
        with sqlite3.connect(self.gpkg_path) as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT settlement_id, answer_text
                FROM answers
                WHERE question_id = ?
                ORDER BY settlement_id, answer_text
            """, (question_id,))
            for settlement_id, answer_text in cur.fetchall():
                sid = int(settlement_id)
                text = str(answer_text).strip()
                if not text:
                    continue
                answers_by_settlement.setdefault(sid, [])
                if text not in answers_by_settlement[sid]:
                    answers_by_settlement[sid].append(text)

        result: List[Dict] = []
        for feature in settlements_layer.getFeatures():
            try:
                settlement_id = int(feature[id_field])
            except Exception:
                continue

            answers = answers_by_settlement.get(settlement_id)
            if not answers:
                continue

            geom = feature.geometry()
            if geom is None or geom.isEmpty():
                continue

            point = geom.asPoint()
            settlement_name = str(feature[name_field])
            answer_count = len(answers)
            is_multivalue = answer_count > 1

            for answer_index, answer_text in enumerate(answers):
                result.append({
                    "settlement_id": settlement_id,
                    "settlement_name": settlement_name,
                    "answer_text": answer_text,
                    "x": point.x(),
                    "y": point.y(),
                    "answer_index": answer_index,
                    "answer_count": answer_count,
                    "is_multivalue": is_multivalue,
                })

        return result

    def get_settlement_questions(self, settlement_id: int) -> List[Tuple[str, str]]:
        if not self.exists():
            return []

        with sqlite3.connect(self.gpkg_path) as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT q.text, a.answer_text
                FROM answers a
                JOIN questions q ON q.id = a.question_id
                WHERE a.settlement_id = ?
                ORDER BY q.id, a.answer_text
            """, (settlement_id,))
            return cur.fetchall()

    def get_settlement_names(self) -> List[str]:
        if not self.exists():
            return []

        with sqlite3.connect(self.gpkg_path) as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT name
                FROM settlements_ref
                ORDER BY name COLLATE NOCASE
            """)
            return [row[0] for row in cur.fetchall() if row[0]]

    def find_settlement_feature_by_name(self, name: str) -> Optional[QgsFeature]:
        settlements_layer = self.get_settlements_layer()
        name_field = self.get_settlement_name_field()

        if settlements_layer is None or not name_field:
            return None

        target = name.strip().casefold()
        if not target:
            return None

        for feature in settlements_layer.getFeatures():
            value = feature[name_field]
            if value is None:
                continue
            if str(value).strip().casefold() == target:
                return feature

        return None

    def get_settlements_layer(self) -> Optional[QgsVectorLayer]:
        layer = self.find_layer_by_name("settlements")
        if layer is None or not layer.isValid():
            return None
        return layer

    def get_settlement_id_field(self) -> Optional[str]:
        layer = self.get_settlements_layer()
        if layer is None:
            return None

        field_names = [field.name() for field in layer.fields()]
        return self._pick_existing_field(
            field_names,
            ["id", "ID", "fid", "FID", "osm_id", "settlement_id"]
        )

    def get_settlement_name_field(self) -> Optional[str]:
        layer = self.get_settlements_layer()
        if layer is None:
            return None

        field_names = [field.name() for field in layer.fields()]
        return self._pick_existing_field(
            field_names,
            ["name", "NAME", "name_ru", "settlement", "locality"]
        )

    def add_service_layer_to_project(self) -> None:
        existing = self.find_layer_by_name(self.service_layer_name)
        if existing is not None:
            return

        layer_uri = f"{self.gpkg_path}|layername={self.service_layer_name}"
        layer = QgsVectorLayer(layer_uri, self.service_layer_name, "ogr")

        if layer.isValid():
            self.project.addMapLayer(layer)

    def find_layer_by_name(self, name: str) -> Optional[QgsVectorLayer]:
        for layer in self.project.mapLayers().values():
            if layer.name() == name:
                return layer
        return None

    def _pick_existing_field(self, existing_fields, candidates) -> Optional[str]:
        for candidate in candidates:
            if candidate in existing_fields:
                return candidate
        return None