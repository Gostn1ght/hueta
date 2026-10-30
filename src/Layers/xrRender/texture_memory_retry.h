#pragma once

// Retry only a failed memory allocation, using lower DDS mips or resizing
// mipless DDS images through the loader's documented target dimensions.
// Successful loads and non-memory errors retain their ordinary behavior.
template<class Info, class Lod, class Create, class Release, class IsMemoryError, class OnRetry>
auto create_texture_with_mip_retry(Info& info, unsigned width, unsigned height, unsigned mips,
                                 Lod& lod, Create create, Release release,
                                 IsMemoryError memory_error, OnRetry on_retry) -> decltype(create())
{
    unsigned retries = 0;
    for (;;)
    {
        const auto result = create();
        if (result >= 0 || !memory_error(result) || retries >= 3 || !width || !height || !mips || mips > 32)
            return result;
        const unsigned current = static_cast<unsigned>(lod);
        if (current >= 31) return result;
        const unsigned next = current + 1;
        const unsigned next_width = width >> next;
        const unsigned next_height = height >> next;
        if (next_width < 4 || next_height < 4) return result;
        release();
        lod = static_cast<Lod>(next);
        info.FirstMipLevel = next < mips ? next : mips - 1;
        info.MipLevels = mips - info.FirstMipLevel;
        info.Width = next_width;
        info.Height = next_height;
        ++retries;
        on_retry();
    }
}
