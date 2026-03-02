#pragma once

#include <filesystem>
#include <optional>
#include <ostream>
#include <string>
#include <vector>
#include <iostream>

namespace hailo_apps {

/**
 * @brief Centralized manager for application resources driven by a YAML config:
 *        - Input resources (images/videos/json/npy) selected by "tag"
 *        - Model HEFs selected by app + device architecture (hailo8/hailo8l/hailo10h)
 *        - Automatic download (S3/ModelZoo/Gen-AI MZ URL builders + explicit URLs)
 *
 * Expected YAML layout (high-level):
 *   videos/images/json/npy: [ { name, description?, url?, source?, tag:[app1, app2, ...] }, ... ]
 *   <app_name>:
 *     models:
 *       hailo8/hailo8l/hailo10h:
 *         default: [ { name, source, url? }, ... ]
 *         extra:   [ { name, source, url? }, ... ]
 *
 * YAML path resolution:
 *   1) env var RESOURCES_YAML (if set)
 *   2) <exe_dir>/config/resources_config.yaml
 */
class ResourcesManager final {
public:
    struct ResourceEntry {
        std::string kind;         // e.g. "images" / "videos" / "json" / "npy"
        std::string name;         // filename (or logical resource name)
        std::string description;  // optional
        std::string url;          // optional explicit URL
        std::string source;       // e.g. "s3" / "mz" / "gen-ai-mz" (for inputs typically "s3")
    };

    struct ModelEntry {
        std::string name;   // model name (without .hef) or possibly with extension depending on YAML
        std::string source; // "mz" / "s3" / "gen-ai-mz"
        std::string url;    // optional explicit URL
    };

    /**
     * @brief Construct a ResourcesManager.
     * @param yaml_path Optional explicit YAML path. If not provided, uses default search logic.
     */
    explicit ResourcesManager(std::optional<std::filesystem::path> yaml_path = std::nullopt);

    // ---------------------------
    // Inputs (images/videos)
    // ---------------------------

    /**
     * @brief Collect inputs for an app (by tag) from YAML.
     * @param app App key (e.g. "object_detection", "pose_estimation", ...)
     * @return vector of matching resources for requested kind(s)
     */
    std::vector<ResourceEntry> list_images(const std::string &app) const;
    std::vector<ResourceEntry> list_videos(const std::string &app) const;

    /**
     * @brief Print inputs (images/videos) to the provided stream.
     */
    void print_inputs(const std::string &app, std::ostream &os = std::cout) const;

    /**
     * @brief Resolve an input argument into a usable input string.
     *
     * Behavior:
     *  - "usb"/"rpi" -> returned as-is (camera mode shortcuts)
     *  - existing path -> returned as absolute path
     *  - empty string  -> auto-select first image else first video from YAML and download it
     *  - "name"        -> treat as resource name from YAML and download it
     *  - "file.ext" (non-existing) -> prints list and throws
     *
     * @param app App key
     * @param input_arg User provided input argument (can be empty)
     * @param target_dir Download directory (default: "inputs")
     * @return resolved input argument (absolute path or "usb"/"rpi")
     */
    std::string resolve_input_arg(const std::string &app,
                                  const std::string &input_arg,
                                  const std::filesystem::path &target_dir = "inputs") const;

    // ---------------------------
    // Models / HEFs
    // ---------------------------

    /**
     * @brief Print models (default + extra) available for current detected device arch.
     * @param app App key
     */
    void print_models(const std::string &app, std::ostream &os = std::cout) const;

    /**
     * @brief Resolve a model/network argument into a .hef path.
     *
     * Behavior:
     *  - existing .hef path -> returned as absolute path
     *  - "name.hef" (missing) -> prints list and throws
     *  - model name -> downloads to dest_dir/<name>.hef (reuses if already present)
     *
     * Device architecture is detected via `hailortcli fw-control identify`.
     *
     * @param app App key
     * @param net_arg User provided network arg (model name or .hef path)
     * @param dest_dir Directory for downloaded HEFs (default: "hefs")
     * @return absolute .hef file path
     */
    std::string resolve_net_arg(const std::string &app,
                                const std::string &net_arg,
                                const std::filesystem::path &dest_dir = "hefs") const;

    /**
     * @brief Best-effort metadata query for a model entry in YAML.
     */
    std::string get_model_meta_value(const std::string &app,
                                       const std::string &model_name,
                                       const std::string &key) const;

    /**
     * @brief Convenience alias used by older code: list networks == list models.
     */
    void print_networks(const std::string &app, std::ostream &os = std::cout) const { print_models(app, os); }

private:
    std::filesystem::path m_yaml_path;

    std::filesystem::path resources_root() const;
    std::filesystem::path models_dir_for_arch(const std::string &hw_arch) const;
    std::filesystem::path inputs_dir_for_kind(const std::string &kind) const;
};

} // namespace hailo_apps