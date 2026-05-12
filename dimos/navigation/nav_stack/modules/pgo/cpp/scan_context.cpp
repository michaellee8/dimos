#include "scan_context.h"

#include <algorithm>
#include <cmath>

namespace scan_context {

Descriptor make_descriptor(const CloudType& cloud, const Config& cfg) {
    Descriptor d = Descriptor::Constant(cfg.n_rings, cfg.n_sectors, 0.0f);
    if (cfg.n_rings <= 0 || cfg.n_sectors <= 0 || cfg.max_range_m <= 0.0) {
        return d;
    }

    const double ring_step = cfg.max_range_m / static_cast<double>(cfg.n_rings);
    const double sector_step = 2.0 * M_PI / static_cast<double>(cfg.n_sectors);

    for (const auto& pt : cloud.points) {
        const double x = pt.x;
        const double y = pt.y;
        const double z = pt.z;

        const double range = std::sqrt(x * x + y * y);
        if (range >= cfg.max_range_m || range <= 1e-6) {
            continue;
        }

        int ring = static_cast<int>(std::floor(range / ring_step));
        if (ring < 0 || ring >= cfg.n_rings) {
            continue;
        }

        double azimuth = std::atan2(y, x);
        if (azimuth < 0.0) {
            azimuth += 2.0 * M_PI;
        }
        int sector = static_cast<int>(std::floor(azimuth / sector_step));
        if (sector < 0) sector = 0;
        if (sector >= cfg.n_sectors) sector = cfg.n_sectors - 1;

        float& cell = d(ring, sector);
        const float zf = static_cast<float>(z);
        if (zf > cell) {
            cell = zf;
        }
    }
    return d;
}

RingKey make_ring_key(const Descriptor& d) {
    RingKey key = RingKey::Zero(d.rows());
    if (d.cols() == 0) return key;
    for (int i = 0; i < d.rows(); i++) {
        key(i) = d.row(i).mean();
    }
    return key;
}

SectorKey make_sector_key(const Descriptor& d) {
    SectorKey key = SectorKey::Zero(d.cols());
    if (d.rows() == 0) return key;
    for (int j = 0; j < d.cols(); j++) {
        key(j) = d.col(j).mean();
    }
    return key;
}

float column_cosine_distance(const Descriptor& query,
                             const Descriptor& candidate,
                             int shift) {
    if (query.rows() != candidate.rows() || query.cols() != candidate.cols()) {
        return 2.0f;
    }
    const int cols = static_cast<int>(query.cols());
    if (cols == 0) return 2.0f;

    float total = 0.0f;
    int valid_cols = 0;
    for (int j = 0; j < cols; j++) {
        const int cj = ((j + shift) % cols + cols) % cols;
        const auto q_col = query.col(j);
        const auto c_col = candidate.col(cj);
        const float q_norm = q_col.norm();
        const float c_norm = c_col.norm();
        if (q_norm <= 1e-6f || c_norm <= 1e-6f) {
            continue;
        }
        const float cos_sim = q_col.dot(c_col) / (q_norm * c_norm);
        total += (1.0f - cos_sim);
        valid_cols++;
    }
    if (valid_cols == 0) return 2.0f;
    return total / static_cast<float>(valid_cols);
}

std::pair<float, int> best_distance(const Descriptor& query,
                                    const Descriptor& candidate) {
    const int cols = static_cast<int>(query.cols());
    float best = 2.0f;
    int best_shift = 0;
    for (int shift = 0; shift < cols; shift++) {
        const float d = column_cosine_distance(query, candidate, shift);
        if (d < best) {
            best = d;
            best_shift = shift;
        }
    }
    return {best, best_shift};
}

}  // namespace scan_context
