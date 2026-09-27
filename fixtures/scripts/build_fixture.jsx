#include "json2.jsx"

/*
 * Fixture builder for the AE 10-skill verification pilot.
 *
 * IMPORTANT:
 * This script intentionally MUTATES a disposable After Effects project.
 * It is fixture preparation, never measured skill execution.
 * It refuses to run unless request.lab_mode is DISPOSABLE_FIXTURE_BUILD.
 */

function readJsonFile(path) {
    var file = new File(path);
    if (!file.exists) throw new Error("Missing file: " + path);
    file.encoding = "UTF-8";
    if (!file.open("r")) throw new Error("Unable to open: " + path);
    var content = file.read();
    file.close();
    if (!content) throw new Error("Empty JSON file: " + path);
    return JSON.parse(content);
}

function writeJsonFile(path, value) {
    var finalFile = new File(path);
    var temporary = new File(path + ".tmp");

    if (temporary.exists) {
        temporary.remove();
    }
    temporary.encoding = "UTF-8";
    if (!temporary.open("w")) throw new Error("Unable to write temporary result: " + path);
    temporary.write(JSON.stringify(value));
    temporary.close();

    if (finalFile.exists && !finalFile.remove()) {
        throw new Error("Unable to replace existing result: " + path);
    }
    if (!temporary.rename(finalFile.name)) {
        throw new Error("Unable to publish result atomically: " + path);
    }
}

function requireValue(condition, message) {
    if (!condition) throw new Error(message);
}

function closeCurrentProjectWithoutSaving() {
    try {
        if (app.project) {
            app.project.close(CloseOptions.DO_NOT_SAVE_CHANGES);
        }
    } catch (error) {
        throw new Error("Unable to close current disposable project: " + error);
    }
}

function ensureNewProject() {
    closeCurrentProjectWithoutSaving();
    var created = app.newProject();
    requireValue(created !== null && app.project, "Unable to create a new project");
}

function setTransformValue(layer, matchName, value) {
    var transform = layer.property("ADBE Transform Group");
    requireValue(transform !== null, "Transform group unavailable for " + layer.name);
    var property = transform.property(matchName);
    requireValue(property !== null, "Property unavailable: " + matchName);
    property.setValue(value);
}

function applyLayerState(layer, layerSpec) {
    layer.name = String(layerSpec.name);

    if (layerSpec.in_seconds !== undefined && layerSpec.in_seconds !== null) {
        layer.inPoint = Number(layerSpec.in_seconds);
    }
    if (layerSpec.out_seconds !== undefined && layerSpec.out_seconds !== null) {
        layer.outPoint = Number(layerSpec.out_seconds);
    }
    if (layerSpec.start_seconds !== undefined && layerSpec.start_seconds !== null) {
        layer.startTime = Number(layerSpec.start_seconds);
    }

    var transform = layerSpec.transform || {};
    var position = transform.position || null;
    if (position && position.x !== null && position.y !== null &&
        position.x !== undefined && position.y !== undefined) {
        setTransformValue(layer, "ADBE Position", [Number(position.x), Number(position.y)]);
    }

    var scale = transform.scale || null;
    if (scale && scale.x_percent !== null && scale.y_percent !== null &&
        scale.x_percent !== undefined && scale.y_percent !== undefined) {
        setTransformValue(
            layer,
            "ADBE Scale",
            [Number(scale.x_percent), Number(scale.y_percent)]
        );
    }

    if (transform.opacity_percent !== undefined && transform.opacity_percent !== null) {
        setTransformValue(layer, "ADBE Opacity", Number(transform.opacity_percent));
    }

    var properties = layerSpec.properties || {};
    var opacity = properties.opacity || {};
    if (opacity.keyframe_count !== undefined && opacity.keyframe_count !== null) {
        requireValue(
            Number(opacity.keyframe_count) === 0,
            "Fixture builder refuses to pre-create measured opacity keyframes"
        );
    }
    if (opacity.keyframes !== undefined && opacity.keyframes !== null) {
        requireValue(
            opacity.keyframes.length === 0,
            "Fixture builder refuses to pre-create measured opacity keyframes"
        );
    }

    if (layerSpec.effects !== undefined && layerSpec.effects !== null) {
        requireValue(
            layerSpec.effects.length === 0,
            "Fixture builder refuses to pre-install measured effects"
        );
    }
}

function createTextLayer(comp, layerSpec) {
    requireValue(layerSpec.type === "text", "Only text layers are supported in baseline fixtures");
    requireValue(typeof layerSpec.source_text === "string", "Text layer source_text is required");
    var layer = comp.layers.addText(String(layerSpec.source_text));
    applyLayerState(layer, layerSpec);
    return layer;
}

function buildFromRequiredState(requiredState) {
    var projectSpec = requiredState.project || {};
    var compositionCount = Number(projectSpec.composition_count);
    requireValue(
        compositionCount === 0 || compositionCount === 1,
        "Fixture builder supports composition_count 0 or 1"
    );

    ensureNewProject();

    if (compositionCount === 0) {
        requireValue(requiredState.active_comp === null, "Empty project requires active_comp=null");
        requireValue(
            requiredState.layers && requiredState.layers.length === 0,
            "Empty project requires zero layers"
        );
        return;
    }

    var compSpec = requiredState.active_comp;
    requireValue(compSpec !== null && compSpec !== undefined, "active_comp is required");

    var comp = app.project.items.addComp(
        String(compSpec.name),
        Number(compSpec.width),
        Number(compSpec.height),
        1.0,
        Number(compSpec.duration_seconds),
        Number(compSpec.frame_rate)
    );

    var layers = requiredState.layers || [];
    /*
     * AE inserts new layers at index 1, so build from bottom to top.
     * This preserves the canonical index order declared in the fixture spec.
     */
    for (var i = layers.length - 1; i >= 0; i--) {
        var layerSpec = layers[i];
        createTextLayer(comp, layerSpec);
    }

    /* Validate final top-to-bottom order after all insertions are complete. */
    for (var j = 0; j < layers.length; j++) {
        var expectedLayer = layers[j];
        var actualLayer = comp.layer(j + 1);
        requireValue(
            actualLayer !== null,
            "Expected layer missing at index " + String(j + 1)
        );
        requireValue(
            String(actualLayer.name) === String(expectedLayer.name),
            "Layer order mismatch at index " + String(j + 1)
        );
        if (expectedLayer.index !== undefined && expectedLayer.index !== null) {
            requireValue(
                actualLayer.index === Number(expectedLayer.index),
                "Declared layer index mismatch for " + String(expectedLayer.name)
            );
        }
    }

    if (compSpec.current_time_seconds !== undefined &&
        compSpec.current_time_seconds !== null) {
        comp.time = Number(compSpec.current_time_seconds);
    } else if (compSpec.current_time_frame !== undefined &&
               compSpec.current_time_frame !== null) {
        comp.time = Number(compSpec.current_time_frame) / Number(compSpec.frame_rate);
    }

    /* Ensure the intended composition is the active item for AE Reader certification. */
    comp.openInViewer();
}

(function () {
    var scriptFile = new File($.fileName);
    var directory = scriptFile.parent;
    var requestPath = directory.fsName + "/request.json";
    var resultPath = directory.fsName + "/build_result.json";
    var result = {
        status: "FAILED",
        fixture_id: null,
        output_path: null,
        saved_at: null,
        ae_version: null,
        ae_build_name: null,
        ae_build_number: null,
        ae_language: null,
        error: null
    };

    try {
        var request = readJsonFile(requestPath);
        requireValue(
            request.lab_mode === "DISPOSABLE_FIXTURE_BUILD",
            "Refusing to mutate project outside disposable fixture-build mode"
        );
        requireValue(
            typeof request.fixture_id === "string" && request.fixture_id.length > 0,
            "fixture_id is required"
        );
        requireValue(
            typeof request.output_path === "string" && request.output_path.length > 4,
            "output_path is required"
        );
        requireValue(
            request.output_path.toLowerCase().substr(request.output_path.length - 4) === ".aep",
            "fixture output must use .aep extension"
        );
        requireValue(
            request.required_state !== null && request.required_state !== undefined,
            "required_state is required"
        );

        result.fixture_id = String(request.fixture_id);
        result.output_path = String(request.output_path);

        try { result.ae_version = String(app.version); } catch (ignored) {}
        try { result.ae_build_name = String(app.buildName); } catch (ignored2) {}
        try { result.ae_build_number = app.buildNumber; } catch (ignored3) {}
        try { result.ae_language = String(app.isoLanguage); } catch (ignored4) {}

        buildFromRequiredState(request.required_state);

        var outputFile = new File(result.output_path);
        requireValue(!outputFile.exists, "Output fixture already exists");
        app.project.save(outputFile);
        requireValue(outputFile.exists, "After Effects did not create the fixture file");

        result.saved_at = (new Date()).getTime() / 1000.0;
        result.status = "SAVED";
    } catch (error) {
        result.status = "FAILED";
        result.error = String(error);
    }

    writeJsonFile(resultPath, result);
}());
