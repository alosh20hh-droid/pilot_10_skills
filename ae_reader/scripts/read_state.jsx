/* AE-R1: read-only After Effects state export. No project mutation APIs are used. */

function safeValue(value) {
    var kind = typeof value;
    if (value === null || kind === "string" || kind === "boolean" || kind === "number") {
        return value;
    }
    if (kind === "object" && value.length !== undefined) {
        var arrayValue = [];
        for (var i = 0; i < value.length; i++) arrayValue.push(safeValue(value[i]));
        return arrayValue;
    }
    return null;
}

function escapeString(value) {
    var text = String(value);
    text = text.replace(/\\/g, "\\\\");
    text = text.replace(/"/g, "\\\"");
    text = text.replace(/\r/g, "\\r");
    text = text.replace(/\n/g, "\\n");
    text = text.replace(/\t/g, "\\t");
    return "\"" + text + "\"";
}

function serialize(value) {
    if (value === null || value === undefined) return "null";
    if (typeof value === "string") return escapeString(value);
    if (typeof value === "number") return isFinite(value) ? String(value) : "null";
    if (typeof value === "boolean") return value ? "true" : "false";
    if (value instanceof Array) {
        var parts = [];
        for (var i = 0; i < value.length; i++) parts.push(serialize(value[i]));
        return "[" + parts.join(",") + "]";
    }
    if (typeof value === "object") {
        var fields = [];
        for (var key in value) {
            if (value.hasOwnProperty(key)) fields.push(escapeString(key) + ":" + serialize(value[key]));
        }
        return "{" + fields.join(",") + "}";
    }
    return "null";
}

function parseRequest(text) {
    /* Refuse to evaluate request text: a local IPC file must never become code. */
    if (typeof JSON !== "undefined" && JSON.parse) return JSON.parse(text);
    throw new Error("JSON.parse is unavailable in this ExtendScript host");
}

function unavailableProperty() {
    return {available:false, name:null, match_name:null, num_keys:0, is_time_varying:false, current_value:null, keys:[]};
}

function readPropertySnapshot(property) {
    if (!property) return unavailableProperty();
    var result = unavailableProperty();
    try {
        result.available = true;
        result.name = property.name;
        result.match_name = property.matchName;
        result.num_keys = property.numKeys;
        result.is_time_varying = property.isTimeVarying;
        result.current_value = safeValue(property.value);
        for (var i = 1; i <= result.num_keys; i++) {
            result.keys.push({index:i, time:property.keyTime(i), value:safeValue(property.keyValue(i))});
        }
    } catch (error) {
        result.available = false;
        result.current_value = null;
    }
    return result;
}

function readPosition(transform) {
    var combined = null;
    try { combined = transform ? transform.property("ADBE Position") : null; } catch (ignored) { combined = null; }
    try {
        if (combined && !combined.dimensionsSeparated) return {mode:"combined", property:readPropertySnapshot(combined), separated:{}};
    } catch (ignored2) {}
    var separated = {};
    var names = ["ADBE Position_0", "ADBE Position_1", "ADBE Position_2"];
    for (var i = 0; i < names.length; i++) {
        var item = null;
        try { item = transform.property(names[i]); } catch (ignored3) { item = null; }
        if (item) separated[names[i]] = readPropertySnapshot(item);
    }
    return {mode:"separated", property:null, separated:separated};
}

function readTransformProperty(transform, matchName) {
    if (!transform) return null;
    try { return transform.property(matchName); } catch (ignored) { return null; }
}

function readLayer(layer) {
    var isText = false;
    try { isText = layer.matchName === "ADBE Text Layer"; } catch (ignored) {}
    var transform = null;
    try { transform = layer.property("ADBE Transform Group"); } catch (ignored2) {}
    return {
        index:layer.index,
        name:String(layer.name),
        match_name:String(layer.matchName),
        locked:Boolean(layer.locked),
        enabled:Boolean(layer.enabled),
        is_text_layer:isText,
        position:readPosition(transform),
        opacity:readPropertySnapshot(readTransformProperty(transform, "ADBE Opacity")),
        scale:readPropertySnapshot(readTransformProperty(transform, "ADBE Scale"))
    };
}

function writeResponse(response) {
    var scriptFile = new File($.fileName);
    var directory = scriptFile.parent;
    var temporary = new File(directory.fsName + "/response.tmp");
    temporary.encoding = "UTF-8";
    temporary.open("w");
    temporary.write(serialize(response));
    temporary.close();
    /* Python removes the prior response before launching this script. */
    temporary.rename("response.json");
}

(function () {
    var scriptFile = new File($.fileName);
    var directory = scriptFile.parent;
    var requestFile = new File(directory.fsName + "/request.json");
    var request = null;
    var response = {
        schema_version:1, status:"INVALID_RESPONSE", request_id:null, session_id:null,
        lesson_id:null, step_id:null, captured_at:null, application:{name:"After Effects"},
        composition:{available:false}, selected_layers:[], errors:[]
    };
    try {
        requestFile.encoding = "UTF-8";
        requestFile.open("r");
        request = parseRequest(requestFile.read());
        requestFile.close();
        response.request_id = String(request.request_id);
        response.session_id = String(request.session_id);
        response.lesson_id = String(request.lesson_id);
        response.step_id = String(request.step_id);
        response.captured_at = (new Date()).getTime() / 1000.0;
        if (!app.project) {
            response.status = "NO_PROJECT";
            response.errors.push("No project is open.");
        } else {
            var item = app.project.activeItem;
            if (item && item instanceof CompItem) {
                response.composition = {
                    available:true, name:String(item.name), width:item.width, height:item.height,
                    duration:item.duration, frame_rate:item.frameRate, time:item.time,
                    num_layers:item.numLayers, selected_layers_count:item.selectedLayers.length
                };
                for (var i = 0; i < item.selectedLayers.length; i++) response.selected_layers.push(readLayer(item.selectedLayers[i]));
                response.status = "OK";
            } else {
                response.status = "NO_ACTIVE_COMPOSITION";
                response.errors.push("The active item is not a composition.");
            }
        }
    } catch (error) {
        response.status = "INVALID_RESPONSE";
        response.errors.push(String(error));
    }
    writeResponse(response);
}());
