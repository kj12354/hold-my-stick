// Camera unit 5 -> SSD MobileNet -> UDP JSON for brain.py.
//
// {"t": <epoch ms>, "objs": [{"cls":"person","score":0.82,"x":0.41,"h":0.55}]}
// Sent every frame, including frames with no objects, to 127.0.0.1:5005.
// Also writes /tmp/latest.jpg about once a second.

#include <camera/camera_api.h>
#include <jpeglib.h>
#include <tensorflow/lite/c/c_api.h>

#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

namespace {

constexpr int kInput = 300;
constexpr int kPort = 5005;
constexpr int kMaxObjs = 10;

struct App {
    TfLiteInterpreter* interpreter = nullptr;
    TfLiteTensor* input = nullptr;
    std::vector<std::string> labels;
    int udp = -1;
    sockaddr_in dest{};
    uint64_t frames = 0;
    uint64_t last_jpg_ms = 0;
    uint64_t window_start_ms = 0;
    uint64_t window_frames = 0;
};

uint64_t epoch_ms() {
    using namespace std::chrono;
    return duration_cast<milliseconds>(system_clock::now().time_since_epoch()).count();
}

std::vector<std::string> load_labels(const char* path) {
    std::ifstream in(path);
    std::vector<std::string> labels;
    std::string line;
    while (std::getline(in, line)) {
        if (!line.empty() && line.back() == '\r') line.pop_back();
        labels.push_back(line);
    }
    if (labels.empty()) {
        std::fprintf(stderr, "no labels in %s\n", path);
        std::exit(1);
    }
    return labels;
}

// The C270 exposes for the bright wall, so a person lands near black and the
// model calls them a chair. Gamma 0.45 lifts those shadows. 20 -> 78, 180 -> 221.
const uint8_t* shadow_lift() {
    static uint8_t lut[256];
    static bool ready = false;
    if (!ready) {
        for (int i = 0; i < 256; ++i) {
            float lifted = std::pow(i / 255.0f, 0.45f) * 255.0f;
            lut[i] = static_cast<uint8_t>(std::lround(std::min(255.0f, lifted)));
        }
        ready = true;
    }
    return lut;
}

void ycbcr_to_rgb300(const uint8_t* src, uint32_t width, uint32_t height, uint32_t stride,
                     uint8_t* dst) {
    if (width < 2 || height < 1) return;
    const uint8_t* lift = shadow_lift();
    for (int y = 0; y < kInput; ++y) {
        int sy = y * static_cast<int>(height) / kInput;
        const uint8_t* row = src + static_cast<uint32_t>(sy) * stride;
        for (int x = 0; x < kInput; ++x) {
            int sx = x * static_cast<int>(width) / kInput;
            sx -= sx & 1;
            const uint8_t* p = row + sx * 2;
            int yy = (sx / 2 * 2 == sx) ? p[0] : p[2];
            int cb = static_cast<int>(p[1]) - 128;
            int cr = static_cast<int>(p[3]) - 128;
            auto clamp = [](int v) { return static_cast<uint8_t>(std::max(0, std::min(255, v))); };
            uint8_t* o = dst + (y * kInput + x) * 3;
            o[0] = lift[clamp(yy + (1436 * cr) / 1024)];
            o[1] = lift[clamp(yy - (352 * cb + 731 * cr) / 1024)];
            o[2] = lift[clamp(yy + (1815 * cb) / 1024)];
        }
    }
}

bool write_jpeg(const char* path, const uint8_t* rgb, int w, int h) {
    FILE* f = std::fopen(path, "wb");
    if (!f) return false;
    jpeg_compress_struct cinfo;
    jpeg_error_mgr jerr;
    cinfo.err = jpeg_std_error(&jerr);
    jpeg_create_compress(&cinfo);
    jpeg_stdio_dest(&cinfo, f);
    cinfo.image_width = w;
    cinfo.image_height = h;
    cinfo.input_components = 3;
    cinfo.in_color_space = JCS_RGB;
    jpeg_set_defaults(&cinfo);
    jpeg_set_quality(&cinfo, 70, TRUE);
    jpeg_start_compress(&cinfo, TRUE);
    while (cinfo.next_scanline < cinfo.image_height) {
        JSAMPROW row = const_cast<JSAMPROW>(rgb + cinfo.next_scanline * w * 3);
        jpeg_write_scanlines(&cinfo, &row, 1);
    }
    jpeg_finish_compress(&cinfo);
    jpeg_destroy_compress(&cinfo);
    std::fclose(f);
    return true;
}

std::string json_escape(const std::string& s) {
    std::string out;
    for (char c : s) {
        if (c == '\\' || c == '"') out.push_back('\\');
        out.push_back(c);
    }
    return out;
}

const float* tensor_floats(const TfLiteTensor* t, int* count) {
    *count = static_cast<int>(TfLiteTensorByteSize(t) / sizeof(float));
    return static_cast<const float*>(TfLiteTensorData(t));
}

void on_frame(camera_handle_t, camera_buffer_t* buf, void* arg) {
    auto* app = static_cast<App*>(arg);
    if (!buf || buf->frametype != CAMERA_FRAMETYPE_YCBYCR || !buf->framebuf) return;
    const auto& d = buf->framedesc.ycbycr;
    if (d.width < 2 || d.height < 1 || d.stride < d.width * 2) return;

    // 270 KB. Keep it off the callback stack, and drop a frame if the
    // previous invoke is still running.
    static uint8_t rgb[kInput * kInput * 3];
    static bool busy = false;
    if (busy) return;
    busy = true;
    ycbcr_to_rgb300(buf->framebuf, d.width, d.height, d.stride, rgb);
    std::memcpy(TfLiteTensorData(app->input), rgb, sizeof(rgb));
    if (TfLiteInterpreterInvoke(app->interpreter) != kTfLiteOk) {
        busy = false;
        return;
    }

    const float* boxes = nullptr;
    const float* first = nullptr;
    const float* second = nullptr;
    int box_n = 0, first_n = 0, second_n = 0, num_n = 0;
    bool saw_num = false;
    const int outputs = TfLiteInterpreterGetOutputTensorCount(app->interpreter);
    static bool logged_outputs = false;
    for (int i = 0; i < outputs; ++i) {
        const TfLiteTensor* t = TfLiteInterpreterGetOutputTensor(app->interpreter, i);
        if (!logged_outputs) {
            std::printf("output %d name=%s type=%d bytes=%zu\n", i,
                        TfLiteTensorName(t) ? TfLiteTensorName(t) : "?",
                        static_cast<int>(TfLiteTensorType(t)), TfLiteTensorByteSize(t));
        }
        if (TfLiteTensorType(t) != kTfLiteFloat32) continue;
        int count = 0;
        const float* data = tensor_floats(t, &count);
        if (count >= kMaxObjs * 4 && !boxes) {
            boxes = data;
            box_n = count / 4;
        } else if (count == 1) {
            saw_num = true;
            num_n = std::max(0, static_cast<int>(data[0]));
        } else if (count >= 1 && count <= kMaxObjs) {
            if (!first) {
                first = data;
                first_n = count;
            } else if (!second) {
                second = data;
                second_n = count;
            }
        }
    }
    if (!logged_outputs) {
        logged_outputs = true;
        std::fflush(stdout);
    }
    const float* classes = first;
    const float* scores = second;
    int class_n = first_n;
    int score_n = second_n;
    // Class ids are whole numbers. Scores sit in [0, 1] and are not. A person
    // is class 1, so "max <= 1" is not enough to tell them apart.
    auto integral = [](const float* v, int n) {
        for (int i = 0; i < n; ++i) {
            if (std::fabs(v[i] - std::round(v[i])) > 0.01f) return false;
        }
        return true;
    };
    if (classes && scores && class_n == score_n && integral(scores, score_n) &&
        !integral(classes, class_n)) {
        std::swap(classes, scores);
    }
    int limit = std::min(box_n, std::min(class_n, score_n));
    if (saw_num) limit = std::min(limit, num_n);

    std::ostringstream json;
    json << "{\"t\":" << epoch_ms() << ",\"objs\":[";
    bool first_obj = true;
    float person_score = 0, person_x = 0, person_h = 0;
    float top_score = 0;
    std::string top_name;
    for (int i = 0; i < limit; ++i) {
        float score = scores[i];
        if (score < 0.2f) continue;
        // This model numbers classes from 0 (person). The label file has a
        // background line at index 0, so person is index 1.
        int id = static_cast<int>(std::lround(classes[i])) + 1;
        if (id <= 0 || id >= static_cast<int>(app->labels.size())) continue;
        const std::string& name = app->labels[id];
        if (name.empty() || name == "???") continue;
        float ymin = boxes[i * 4 + 0];
        float xmin = boxes[i * 4 + 1];
        float ymax = boxes[i * 4 + 2];
        float xmax = boxes[i * 4 + 3];
        float x = (xmin + xmax) / 2.0f;
        float h = ymax - ymin;
        if (!first_obj) json << ',';
        first_obj = false;
        json << "{\"cls\":\"" << json_escape(name) << "\",\"score\":" << score
             << ",\"x\":" << x << ",\"h\":" << h << "}";
        if (score > top_score) {
            top_score = score;
            top_name = name;
        }
        if (name == "person" && score > person_score) {
            person_score = score;
            person_x = x;
            person_h = h;
        }
    }
    json << "]}";
    std::string packet = json.str();
    sendto(app->udp, packet.data(), packet.size(), 0,
           reinterpret_cast<sockaddr*>(&app->dest), sizeof(app->dest));

    uint64_t now = epoch_ms();
    if (now - app->last_jpg_ms >= 1000) {
        write_jpeg("/tmp/latest.jpg", rgb, kInput, kInput);
        app->last_jpg_ms = now;
    }
    app->frames++;
    app->window_frames++;
    if (app->window_start_ms == 0) app->window_start_ms = now;
    if (now - app->window_start_ms >= 1000) {
        double fps = app->window_frames * 1000.0 / (now - app->window_start_ms);
        int raw_n = 0;
        if (classes && scores && boxes) raw_n = std::min(box_n, std::min(class_n, score_n));
        std::printf("%.0f fps  num %d  raw", fps, num_n);
        for (int i = 0; i < raw_n && i < 4; ++i) {
            float rh = boxes[i * 4 + 2] - boxes[i * 4 + 0];
            std::printf("  [%.0f %.2f h%.2f]", classes[i], scores[i], rh);
        }
        if (person_score >= 0.5f) {
            std::printf("  PERSON %.2f\n", person_score);
        } else if (!top_name.empty()) {
            std::printf("  top %s %.2f\n", top_name.c_str(), top_score);
        } else {
            std::printf("  no person\n");
        }
        std::fflush(stdout);
        app->window_start_ms = now;
        app->window_frames = 0;
    }
    busy = false;
}

}  // namespace

int main(int argc, char** argv) {
    const char* model_path = argc > 1 ? argv[1] : "detect.tflite";
    const char* label_path = argc > 2 ? argv[2] : "labelmap.txt";
    int unit = argc > 3 ? std::atoi(argv[3]) : 5;

    App app;
    app.labels = load_labels(label_path);
    TfLiteModel* model = TfLiteModelCreateFromFile(model_path);
    if (!model) {
        std::fprintf(stderr, "cannot load model %s\n", model_path);
        return 1;
    }
    TfLiteInterpreterOptions* options = TfLiteInterpreterOptionsCreate();
    TfLiteInterpreterOptionsSetNumThreads(options, 4);
    app.interpreter = TfLiteInterpreterCreate(model, options);
    TfLiteInterpreterOptionsDelete(options);
    TfLiteModelDelete(model);
    if (!app.interpreter || TfLiteInterpreterAllocateTensors(app.interpreter) != kTfLiteOk) {
        std::fprintf(stderr, "interpreter setup failed\n");
        return 1;
    }
    app.input = TfLiteInterpreterGetInputTensor(app.interpreter, 0);
    if (!app.input || TfLiteTensorByteSize(app.input) != kInput * kInput * 3) {
        std::fprintf(stderr, "expected uint8 300x300x3 input, got %zu bytes\n",
                     app.input ? TfLiteTensorByteSize(app.input) : 0);
        return 1;
    }

    app.udp = socket(AF_INET, SOCK_DGRAM, 0);
    app.dest.sin_family = AF_INET;
    app.dest.sin_port = htons(kPort);
    inet_pton(AF_INET, "127.0.0.1", &app.dest.sin_addr);

    camera_handle_t cam = CAMERA_HANDLE_INVALID;
    camera_error_t err = camera_open(static_cast<camera_unit_t>(unit), CAMERA_MODE_RO, &cam);
    if (err != CAMERA_EOK) {
        std::fprintf(stderr, "camera_open unit %d failed: %d\n", unit, err);
        return 1;
    }
    err = camera_set_vf_property(cam,
                                 CAMERA_IMGPROP_FORMAT, CAMERA_FRAMETYPE_YCBYCR,
                                 CAMERA_IMGPROP_WIDTH, 640,
                                 CAMERA_IMGPROP_HEIGHT, 480,
                                 CAMERA_IMGPROP_FRAMERATE, 15.0,
                                 CAMERA_IMGPROP_CREATEWINDOW, 1);
    if (err != CAMERA_EOK) {
        std::fprintf(stderr, "windowed viewfinder failed: %d, continuing without a window\n", err);
        err = camera_set_vf_property(cam,
                                     CAMERA_IMGPROP_FORMAT, CAMERA_FRAMETYPE_YCBYCR,
                                     CAMERA_IMGPROP_WIDTH, 640,
                                     CAMERA_IMGPROP_HEIGHT, 480,
                                     CAMERA_IMGPROP_FRAMERATE, 15.0,
                                     CAMERA_IMGPROP_CREATEWINDOW, 0);
        if (err != CAMERA_EOK) {
            std::fprintf(stderr, "camera_set_vf_property failed: %d\n", err);
            return 1;
        }
    }
    err = camera_start_viewfinder(cam, on_frame, nullptr, &app);
    if (err != CAMERA_EOK) {
        std::fprintf(stderr, "camera_start_viewfinder failed: %d\n", err);
        return 1;
    }
    std::printf("detect running on camera unit %d, udp 127.0.0.1:%d\n", unit, kPort);
    std::fflush(stdout);
    for (;;) pause();
}
