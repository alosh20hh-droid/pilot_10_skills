#include "json2.jsx"

/*
 * AE Reader v2.0.0
 * Read-only After Effects state export for the pilot verification lab.
 * Project mutation APIs are intentionally absent from this file.
 */

function safeValue(value) {
    var kind = typeof value;
    if (value === null || kind === "string" || kind === "boolean" || kind === "number") {
        return value;
    }
    if (kind === "object" && value.length !== undefined) {
        var arrayValue = [];
        for (var i = 0; i < value.length; i++) {
            arrayValue.push(safeValue(value[i]));
        }
        return arrayValue;
    }
    return null;
}

function unavailableProperty() {
    return {
        available: false,
        name: null,
        match_name: null,
        num_keys: 0,
        is_time_varying: false,
        current_value: null,
        keys: []
    };
}

function frameForTime(timeSeconds, comp) {
    try {
        if (!comp || !comp.frameDuration || comp.frameDuration <= 0) {
            return null;
        }
        return Math.round(timeSeconds / comp.frameDuration);
    } catch (ignored) {
        return null;
    }
}

function readPropertySnapshot(property, comp) {
    if (!property) {
        return unavailableProperty();
    }

    var result = unavailableProperty();
    try {
        result.available = true;
        result.name = String(property.name);
        result.match_name = String(property.matchName);
        result.num_keys = property.numKeys;
        result.is_time_varying = Boolean(property.isTimeVarying);

        try {
            result.current_value = safeValue(property.value);
        } catch (valueError) {
            result.current_value = null;
        }

        for (var i = 1; i <= result.num_keys; i++) {
            var keyTime = null;
            var keyValue = null;
            try {
                keyTime = property.keyTime(i);
            } catch (timeError) {}
            try {
                keyValue = safeValue(property.keyValue(i));
            } catch (keyValueError) {}

            result.keys.push({
                index: i,
                time_seconds: keyTime,
                frame: keyTime === null ? null : frameForTime(keyTime, comp),
                value: keyValue
            });
        }
    } catch (error) {
        return unavailableProperty();
    }

    return result;
}

function readPosition(transform, comp) {
    if (!transform) {
        return {mode: "unavailable", property: null, separated: {}};
    }

    var combined = null;
    try {
        combined = transform.property("ADBE Position");
    } catch (ignored) {
        combined = null;
    }

    if (combined) {
        try {
            if (!combined.dimensionsSeparated) {
                return {
                    mode: "combined",
                    property: readPropertySnapshot(combined, comp),
                    separated: {}
                };
            }
        } catch (ignored2) {
            return {
                mode: "combined",
                property: readPropertySnapshot(combined, comp),
                separated: {}
            };
        }
    }

    var separated = {};
    var found = false;
    var names = ["ADBE Position_0", "ADBE Position_1", "ADBE Position_2"];

    for (var i = 0; i < names.length; i++) {
        var item = null;
        try {
            item = transform.property(names[i]);
        } catch (ignored3) {
            item = null;
        }
        if (item) {
            found = true;
            separated[names[i]] = readPropertySnapshot(item, comp);
        }
    }

    if (!found) {
        return {mode: "unavailable", property: null, separated: {}};
    }

    return {mode: "separated", property: null, separated: separated};
}

function readTransformProperty(transform, matchName) {
    if (!transform) {
        return null;
    }
    try {
        return transform.property(matchName);
    } catch (ignored) {
        return null;
    }
}

function readLayerType(layer) {
    var matchName = "";
    try {
        matchName = String(layer.matchName);
    } catch (ignored) {}

    if (matchName === "ADBE Text Layer") {
        return "text";
    }
    if (matchName === "ADBE Vector Layer") {
        return "shape";
    }
    if (matchName === "ADBE Camera Layer") {
        return "camera";
    }
    if (matchName === "ADBE Light Layer") {
        return "light";
    }
    if (matchName === "ADBE AV Layer") {
        try {
            if (layer.nullLayer) {
                return "null";
            }
            if (layer.adjustmentLayer) {
                return "adjustment";
            }
            if (layer.guideLayer) {
                return "guide";
            }
            if (layer.source instanceof CompItem) {
                return "precomp";
            }
            if (layer.source && layer.source.mainSource instanceof SolidSource) {
                return "solid";
            }
            if (layer.source && layer.source.mainSource instanceof PlaceholderSource) {
                return "placeholder";
            }
            if (layer.source && layer.source.mainSource instanceof FileSource) {
                if (layer.source.footageMissing) {
                    return "missing";
                }
                if (!layer.source.hasVideo && layer.source.hasAudio) {
                    return "audio";
                }
                return "footage";
            }
        } catch (ignored2) {}
        return "av";
    }

    return "unknown";
}

function readSourceText(layer) {
    try {
        if (String(layer.matchName) !== "ADBE Text Layer") {
            return null;
        }
        var textGroup = layer.property("ADBE Text Properties");
        var textProperty = textGroup ? textGroup.property("ADBE Text Document") : null;
        if (!textProperty) {
            return null;
        }
        var textDocument = textProperty.value;
        if (!textDocument) {
            return null;
        }
        return String(textDocument.text);
    } catch (ignored) {
        return null;
    }
}

function readEffectPropertyNode(property, comp, depth) {
    var result = {
        name: "",
        match_name: "",
        value: null,
        num_keys: 0,
        keys: [],
        properties: []
    };

    try {
        result.name = String(property.name);
    } catch (ignored) {}
    try {
        result.match_name = String(property.matchName);
    } catch (ignored2) {}

    if (depth > 12) {
        return result;
    }

    try {
        if (property.propertyType === PropertyType.PROPERTY) {
            var snapshot = readPropertySnapshot(property, comp);
            result.value = snapshot.current_value;
            result.num_keys = snapshot.num_keys;
            result.keys = snapshot.keys;
            return result;
        }
    } catch (ignored3) {}

    var count = 0;
    try {
        count = property.numProperties;
    } catch (ignored4) {
        count = 0;
    }

    for (var i = 1; i <= count; i++) {
        try {
            result.properties.push(readEffectPropertyNode(property.property(i), comp, depth + 1));
        } catch (ignored5) {}
    }

    return result;
}

function readEffects(layer, comp) {
    var result = [];
    var effects = null;

    try {
        effects = layer.property("ADBE Effect Parade");
    } catch (ignored) {
        effects = null;
    }

    if (!effects) {
        return result;
    }

    var count = 0;
    try {
        count = effects.numProperties;
    } catch (ignored2) {
        count = 0;
    }

    for (var i = 1; i <= count; i++) {
        try {
            var effect = effects.property(i);
            var effectData = {
                name: String(effect.name),
                match_name: String(effect.matchName),
                enabled: Boolean(effect.enabled),
                properties: []
            };

            for (var p = 1; p <= effect.numProperties; p++) {
                effectData.properties.push(readEffectPropertyNode(effect.property(p), comp, 0));
            }
            result.push(effectData);
        } catch (effectError) {}
    }

    return result;
}

function readLayer(layer, comp) {
    var transform = null;
    try {
        transform = layer.property("ADBE Transform Group");
    } catch (ignored) {
        transform = null;
    }

    var layerId = null;
    try {
        if (layer.id !== undefined && layer.id !== null) {
            layerId = layer.id;
        }
    } catch (ignored2) {}

    var selected = false;
    try {
        selected = Boolean(layer.selected);
    } catch (ignored3) {}

    var inSeconds = null;
    var outSeconds = null;
    var startSeconds = null;
    try {
        inSeconds = layer.inPoint;
    } catch (ignored4) {}
    try {
        outSeconds = layer.outPoint;
    } catch (ignored5) {}
    try {
        startSeconds = layer.startTime;
    } catch (ignored6) {}

    return {
        index: layer.index,
        layer_id: layerId,
        name: String(layer.name),
        match_name: String(layer.matchName),
        layer_type: readLayerType(layer),
        selected: selected,
        locked: Boolean(layer.locked),
        enabled: Boolean(layer.enabled),
        source_text: readSourceText(layer),
        in_seconds: inSeconds,
        out_seconds: outSeconds,
        start_seconds: startSeconds,
        position: readPosition(transform, comp),
        opacity: readPropertySnapshot(readTransformProperty(transform, "ADBE Opacity"), comp),
        scale: readPropertySnapshot(readTransformProperty(transform, "ADBE Scale"), comp),
        effects: readEffects(layer, comp)
    };
}

function countCompositions(project) {
    var count = 0;
    for (var i = 1; i <= project.numItems; i++) {
        try {
            if (project.item(i) instanceof CompItem) {
                count++;
            }
        } catch (ignored) {}
    }
    return count;
}

function readApplicationInfo() {
    var info = {
        name: "After Effects",
        version: null,
        build_name: null,
        build_number: null,
        language: null
    };

    try {
        info.version = String(app.version);
    } catch (ignored) {}
    try {
        info.build_name = String(app.buildName);
    } catch (ignored2) {}
    try {
        info.build_number = app.buildNumber;
    } catch (ignored3) {}
    try {
        info.language = String(app.isoLanguage);
    } catch (ignored4) {}

    return info;
}

function readJsonFile(path) {
    var file = new File(path);
    if (!file.exists) {
        throw new Error("Required IPC file not found: " + path);
    }
    file.encoding = "UTF-8";
    if (!file.open("r")) {
        throw new Error("Unable to open IPC file: " + path);
    }
    var content = file.read();
    file.close();
    if (!content || content.length === 0) {
        throw new Error("IPC file is empty: " + path);
    }
    return JSON.parse(content);
}

function writeResponse(response) {
    /*
     * captured_at marks publication of the completed snapshot, not the start
     * of collection. This makes freshness checks conservative and unambiguous.
     */
    response.captured_at = (new Date()).getTime() / 1000.0;
    var scriptFile = new File($.fileName);
    var directory = scriptFile.parent;
    var temporary = new File(directory.fsName + "/response.tmp");
    var finalFile = new File(directory.fsName + "/response.json");

    temporary.encoding = "UTF-8";
    if (!temporary.open("w")) {
        throw new Error("Unable to create response.tmp");
    }
    temporary.write(JSON.stringify(response));
    temporary.close();

    if (finalFile.exists) {
        finalFile.remove();
    }
    if (!temporary.rename("response.json")) {
        throw new Error("Unable to publish response.json");
    }
}

(function () {
    var scriptFile = new File($.fileName);
    var directory = scriptFile.parent;
    var request = null;
    var capabilities = null;

    var response = {
        schema_version: 2,
        reader_version: "2.1.0",
        status: "INVALID_RESPONSE",
        request_id: "",
        run_id: "",
        captured_at: null,
        application: readApplicationInfo(),
        capabilities: {
            reader_version: "2.1.0",
            schema_version: 2,
            supported_capabilities: []
        },
        project: {item_count: 0, composition_count: 0, file_path: null},
        composition: {available: false, selected_layers_count: 0},
        layers: [],
        errors: [],
        session_id: null,
        lesson_id: null,
        step_id: null
    };

    try {
        request = readJsonFile(directory.fsName + "/request.json");
        capabilities = readJsonFile(directory.fsName + "/capabilities.json");

        response.request_id = String(request.request_id);
        response.run_id = String(request.run_id);
        response.session_id = request.session_id === undefined ? null : request.session_id;
        response.lesson_id = request.lesson_id === undefined ? null : request.lesson_id;
        response.step_id = request.step_id === undefined ? null : request.step_id;
        response.capabilities = capabilities;
        if (!app.project) {
            response.status = "NO_PROJECT";
            response.errors.push("No project is open.");
            writeResponse(response);
            return;
        }

        response.project.item_count = app.project.numItems;
        response.project.composition_count = countCompositions(app.project);
        try {
            response.project.file_path = app.project.file ? String(app.project.file.fsName) : null;
        } catch (projectFileError) {
            response.project.file_path = null;
        }

        var item = app.project.activeItem;
        if (!item || !(item instanceof CompItem)) {
            /*
             * A valid empty project has no active composition. This is a
             * measurable pilot state (FX-001), not a reader failure.
             */
            response.status = "OK";
            writeResponse(response);
            return;
        }

        var itemId = null;
        try {
            itemId = item.id;
        } catch (ignored) {}

        response.composition = {
            available: true,
            item_id: itemId,
            name: String(item.name),
            width: item.width,
            height: item.height,
            duration: item.duration,
            frame_rate: item.frameRate,
            time_seconds: item.time,
            time_frame: frameForTime(item.time, item),
            num_layers: item.numLayers,
            selected_layers_count: item.selectedLayers.length
        };

        for (var i = 1; i <= item.numLayers; i++) {
            response.layers.push(readLayer(item.layer(i), item));
        }

        response.status = "OK";
    } catch (error) {
        response.status = "INVALID_RESPONSE";
        response.errors.push(String(error));
    }

    writeResponse(response);
}());
