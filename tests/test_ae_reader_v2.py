import copy
import json
import tempfile
import time
import unittest
from pathlib import Path

from ae_reader import (
    AECapabilityManifest,
    AEReadRequest,
    AEStateSnapshot,
    AfterEffectsReadOnlyObserver,
    READER_VERSION,
    SCHEMA_VERSION,
)
from ae_reader.contract_check import check_contract


REQUIRED_PILOT_CAPABILITIES = {
    "project.composition_count",
    "project.file_identity",
    "composition.identity",
    "composition.dimensions",
    "composition.duration",
    "composition.frame_rate",
    "composition.current_time",
    "layer.list",
    "layer.identity",
    "layer.type",
    "layer.source_text",
    "layer.index",
    "layer.timing",
    "layer.transform.position",
    "layer.transform.scale",
    "layer.transform.opacity",
    "property.keyframes.count",
    "property.keyframes.time",
    "property.keyframes.value",
    "effect.list",
    "effect.identity.stable_id",
    "effect.property.identity",
    "effect.property.value",
}


def sample_response(*, request_id="req-1", run_id="run-1", captured_at=None):
    captured_at = time.time() if captured_at is None else captured_at
    return {
        "schema_version": SCHEMA_VERSION,
        "reader_version": READER_VERSION,
        "status": "OK",
        "request_id": request_id,
        "run_id": run_id,
        "captured_at": captured_at,
        "application": {
            "name": "After Effects",
            "version": "26.0",
            "language": "en-US",
        },
        "capabilities": {
            "reader_version": READER_VERSION,
            "schema_version": SCHEMA_VERSION,
            "supported_capabilities": sorted(REQUIRED_PILOT_CAPABILITIES),
        },
        "project": {
            "item_count": 1,
            "composition_count": 1,
            "file_path": r"C:\\fixtures\\FX-TEST.aep",
        },
        "composition": {
            "available": True,
            "item_id": 101,
            "name": "PILOT_COMP",
            "width": 1920,
            "height": 1080,
            "duration": 5,
            "frame_rate": 30,
            "time_seconds": 1,
            "time_frame": 30,
            "num_layers": 1,
            "selected_layers_count": 1,
        },
        "layers": [
            {
                "index": 1,
                "layer_id": 501,
                "name": "PILOT_TEXT",
                "match_name": "ADBE Text Layer",
                "layer_type": "text",
                "selected": True,
                "locked": False,
                "enabled": True,
                "source_text": "PILOT TEST",
                "in_seconds": 0,
                "out_seconds": 5,
                "start_seconds": 0,
                "position": {
                    "mode": "combined",
                    "property": {
                        "available": True,
                        "name": "Position",
                        "match_name": "ADBE Position",
                        "num_keys": 0,
                        "is_time_varying": False,
                        "current_value": [960, 540],
                        "keys": [],
                    },
                    "separated": {},
                },
                "opacity": {
                    "available": True,
                    "name": "Opacity",
                    "match_name": "ADBE Opacity",
                    "num_keys": 2,
                    "is_time_varying": True,
                    "current_value": 100,
                    "keys": [
                        {"index": 1, "time_seconds": 0, "frame": 0, "value": 0},
                        {"index": 2, "time_seconds": 1, "frame": 30, "value": 100},
                    ],
                },
                "scale": {
                    "available": True,
                    "name": "Scale",
                    "match_name": "ADBE Scale",
                    "num_keys": 0,
                    "is_time_varying": False,
                    "current_value": [125, 125],
                    "keys": [],
                },
                "effects": [
                    {
                        "name": "Gaussian Blur",
                        "match_name": "ADBE Gaussian Blur 2",
                        "enabled": True,
                        "properties": [
                            {
                                "name": "Blurriness",
                                "match_name": "ADBE Gaussian Blur 2-0001",
                                "value": 25,
                                "num_keys": 0,
                                "keys": [],
                                "properties": [],
                            }
                        ],
                    }
                ],
            }
        ],
        "errors": [],
        "session_id": None,
        "lesson_id": None,
        "step_id": None,
    }


class SchemaTests(unittest.TestCase):
    def test_sample_response_parses_and_maps_to_pilot(self):
        snapshot = AEStateSnapshot.from_dict(sample_response())
        state = snapshot.to_pilot_state()

        self.assertEqual(state["project"]["composition_count"], 1)
        self.assertEqual(state["project"]["file_path"], r"C:\\fixtures\\FX-TEST.aep")
        self.assertEqual(state["active_comp"]["current_time_frame"], 30)
        self.assertEqual(state["layers"][0]["transform"]["position"], {"x": 960.0, "y": 540.0})
        self.assertEqual(state["layers"][0]["transform"]["scale"], {"x_percent": 125.0, "y_percent": 125.0})
        self.assertEqual(state["layers"][0]["properties"]["opacity"]["keyframe_count"], 2)
        self.assertEqual(state["layers"][0]["effects"][0]["stable_id"], "ADBE Gaussian Blur 2")

    def test_effect_property_can_be_found_by_stable_id(self):
        snapshot = AEStateSnapshot.from_dict(sample_response())
        effect = snapshot.layers[0].effects[0]
        prop = effect.find_property(match_name="ADBE Gaussian Blur 2-0001")
        self.assertIsNotNone(prop)
        self.assertEqual(prop.value, 25)


    def test_non_string_reader_error_is_rejected(self):
        data = sample_response()
        data["errors"] = [123]
        with self.assertRaises(ValueError):
            AEStateSnapshot.from_dict(data)

    def test_effect_property_key_count_mismatch_is_rejected(self):
        data = sample_response()
        prop = data["layers"][0]["effects"][0]["properties"][0]
        prop["num_keys"] = 1
        prop["keys"] = []
        with self.assertRaises(ValueError):
            AEStateSnapshot.from_dict(data)


    def test_layer_count_mismatch_is_rejected(self):
        data = sample_response()
        data["composition"]["num_layers"] = 2
        with self.assertRaises(ValueError):
            AEStateSnapshot.from_dict(data)

    def test_duplicate_layer_identity_is_rejected(self):
        data = sample_response()
        duplicate = copy.deepcopy(data["layers"][0])
        duplicate["index"] = 2
        duplicate["name"] = "OTHER_LAYER"
        data["layers"].append(duplicate)
        data["composition"]["num_layers"] = 2
        data["composition"]["selected_layers_count"] = 2
        with self.assertRaises(ValueError):
            AEStateSnapshot.from_dict(data)

    def test_layer_without_stable_identity_is_rejected(self):
        data = sample_response()
        data["layers"][0]["layer_id"] = None
        with self.assertRaises(ValueError):
            AEStateSnapshot.from_dict(data)

    def test_selected_layer_count_mismatch_is_rejected(self):
        data = sample_response()
        data["composition"]["selected_layers_count"] = 0
        with self.assertRaises(ValueError):
            AEStateSnapshot.from_dict(data)

    def test_duplicate_layer_name_is_ambiguous_and_fail_closed(self):
        data = sample_response()
        duplicate = dict(data["layers"][0])
        duplicate["index"] = 2
        duplicate["layer_id"] = 502
        data["layers"].append(duplicate)
        data["composition"]["num_layers"] = 2

        snapshot = AEStateSnapshot.from_dict(data)
        self.assertIsNone(snapshot.find_layer("PILOT_TEXT"))


class ManifestTests(unittest.TestCase):
    def test_capability_manifest_covers_pilot(self):
        path = Path("ae_reader/capabilities.json")
        manifest = AECapabilityManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))
        self.assertEqual(manifest.reader_version, READER_VERSION)
        self.assertEqual(manifest.schema_version, SCHEMA_VERSION)
        self.assertEqual(manifest.missing(REQUIRED_PILOT_CAPABILITIES), [])


class ContractAlignmentTests(unittest.TestCase):
    def test_pilot_contract_matches_reader_manifest(self):
        self.assertEqual(check_contract(), [])


class FreshnessTests(unittest.TestCase):
    def test_stale_response_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            observer = AfterEffectsReadOnlyObserver(ipc_dir=temp_dir)
            requested_at = time.time()
            request = AEReadRequest(
                request_id="req-stale",
                run_id="run-stale",
                requested_at=requested_at,
            )
            request_dir = observer._request_directory(request)
            request_dir.mkdir(parents=True)
            data = sample_response(
                request_id=request.request_id,
                run_id=request.run_id,
                captured_at=requested_at - 5,
            )
            data["capabilities"] = observer.capability_manifest.to_dict()
            (request_dir / "response.json").write_text(json.dumps(data), encoding="utf-8")

            response = observer._read_response(request, request_dir)
            self.assertEqual(response.status, "STALE_RESPONSE")

    def test_request_id_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            observer = AfterEffectsReadOnlyObserver(ipc_dir=temp_dir)
            request = AEReadRequest(
                request_id="req-a",
                run_id="run-a",
                requested_at=time.time() - 1,
            )
            request_dir = observer._request_directory(request)
            request_dir.mkdir(parents=True)
            data = sample_response(request_id="req-b", run_id=request.run_id)
            data["capabilities"] = observer.capability_manifest.to_dict()
            (request_dir / "response.json").write_text(json.dumps(data), encoding="utf-8")

            response = observer._read_response(request, request_dir)
            self.assertEqual(response.status, "STALE_RESPONSE")


class SafetyTests(unittest.TestCase):
    def test_jsx_contains_no_project_mutation_calls(self):
        source = Path("ae_reader/scripts/read_state.jsx").read_text(encoding="utf-8")
        forbidden = [
            ".setValue(",
            ".setValueAtTime(",
            ".setValuesAtTimes(",
            ".addProperty(",
            ".addComp(",
            ".duplicate(",
            ".moveBefore(",
            ".moveAfter(",
            "app.executeCommand(",
            "app.beginUndoGroup(",
        ]
        for token in forbidden:
            self.assertNotIn(token, source, token)

    def test_jsx_uses_local_json_parser(self):
        source = Path("ae_reader/scripts/read_state.jsx").read_text(encoding="utf-8")
        self.assertIn('#include "json2.jsx"', source)
        self.assertTrue(Path("ae_reader/scripts/json2.jsx").is_file())


if __name__ == "__main__":
    unittest.main()
