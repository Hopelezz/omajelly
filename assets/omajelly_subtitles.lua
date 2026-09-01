local mp = require "mp"
local input = require "mp.input"
local options = require "mp.options"
local utils = require "mp.utils"

local config = {
    helper = "",
    rating_keys = "",
    language = "en",
    output_directory = "",
}

options.read_options(config, "omajelly_subtitles")

local busy = false
local rating_keys = {}
for key in config.rating_keys:gmatch("[^:]+") do
    if key:match("^[0-9a-fA-F%-][0-9a-fA-F%-]+$") and #key >= 8 then
        rating_keys[#rating_keys + 1] = key
    end
end

local function message(text)
    mp.osd_message(text, 3)
end

local function run_helper(arguments, done)
    local command = {config.helper}
    for _, value in ipairs(arguments) do
        command[#command + 1] = value
    end
    mp.command_native_async({
        name = "subprocess",
        args = command,
        playback_only = true,
        capture_stdout = true,
        capture_stderr = true,
        capture_size = 256 * 1024,
    }, function(success, result, error)
        if not success or not result or result.status ~= 0 then
            local detail = result and result.stderr or error or "Subtitle request failed"
            detail = tostring(detail):gsub("[%c{}\\]", " "):sub(1, 180)
            done(nil, detail ~= "" and detail or "Subtitle request failed")
            return
        end
        local document = utils.parse_json(result.stdout or "")
        if type(document) ~= "table" then
            done(nil, "Jellyfin returned invalid subtitle data")
            return
        end
        done(document, nil)
    end)
end

local function result_label(item)
    local label = item.perfectMatch and "★ " or ""
    label = label .. tostring(item.label or "Subtitle")
    if item.hearingImpaired then label = label .. " [SDH]" end
    if item.forced then label = label .. " [forced]" end
    if item.provider and item.provider ~= "" then
        label = label .. " · " .. item.provider
    end
    return label
end

local function select_result(rating_key, playlist_position, item)
    if mp.get_property_number("playlist-pos", -1) ~= playlist_position then
        message("The playing episode changed; search again")
        return
    end
    busy = true
    message("Downloading subtitle…")
    run_helper({
        "subtitle-download",
        "--rating-key", rating_key,
        "--subtitle-key", tostring(item.key or ""),
        "--format", tostring(item.format or "srt"),
        "--output-directory", config.output_directory,
    }, function(document, error)
        busy = false
        if error then
            message(error)
            return
        end
        if mp.get_property_number("playlist-pos", -1) ~= playlist_position then
            message("Subtitle saved; the playing episode changed")
            return
        end
        local path = tostring(document.path or "")
        if path:sub(1, #config.output_directory + 1) ~= config.output_directory .. "/" then
            message("Jellyfin returned an invalid subtitle file")
            return
        end
        mp.commandv(
            "sub-add",
            path,
            "select",
            tostring(item.label or "Jellyfin subtitle"),
            tostring(item.language or config.language)
        )
        message("Subtitle selected")
    end)
end

local function search_subtitles()
    if busy then
        message("A subtitle request is already running")
        return
    end
    local playlist_position = mp.get_property_number("playlist-pos", -1)
    local rating_key = rating_keys[playlist_position + 1]
    if not rating_key then
        message("Subtitle search is unavailable for this item")
        return
    end
    busy = true
    message("Searching Jellyfin subtitles…")
    run_helper({
        "subtitle-search",
        "--rating-key", rating_key,
        "--language", config.language,
    }, function(document, error)
        busy = false
        if error then
            message(error)
            return
        end
        if mp.get_property_number("playlist-pos", -1) ~= playlist_position then
            message("The playing episode changed; search again")
            return
        end
        local results = document.items
        if type(results) ~= "table" or #results == 0 then
            message("No " .. config.language .. " subtitles found")
            return
        end
        if #results > 40 then
            message("Jellyfin returned too many subtitle results")
            return
        end
        local labels = {}
        for index, item in ipairs(results) do
            if type(item) ~= "table"
                or tostring(item.key or "") == ""
                or tostring(item.key or ""):find("[/\\]") then
                message("Jellyfin returned invalid subtitle data")
                return
            end
            labels[index] = result_label(item)
        end
        input.select({
            prompt = "Search Jellyfin subtitles (" .. config.language .. "):",
            items = labels,
            submit = function(index)
                select_result(rating_key, playlist_position, results[index])
            end,
        })
    end)
end

if config.helper ~= ""
    and config.output_directory:match("^/tmp/omajelly%-player%-")
    and #rating_keys > 0
    and config.language:match("^[a-z][a-z]$") then
    mp.add_forced_key_binding("Ctrl+j", "omajelly-search-subtitles", search_subtitles)
    mp.add_key_binding(nil, "search-subtitles", search_subtitles)
end
