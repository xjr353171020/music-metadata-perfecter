from mutagen.flac import FLAC

# path = "Vladimir Ashkenazy - 12 Etudes, op. 10No. 9 in F minor.flac"
path = "已转换_Bavarian Radio Symphony Orchestra, Internationale Musikinstitut Darmstardt, Sudwesfunk Orchestra - Jupiter and Beyond Requiem for Soprano, Mezzo Soprano, Two Mixed Cho (1).flac"

audio = FLAC(path)

# print("时长:", audio.info.length)
# print("采样率:", audio.info.sample_rate)
# print("声道:", audio.info.channels)
# print("位深:", audio.info.bits_per_sample)

print("\n标签:")
for key, values in audio.tags.items():
    print(key, "=>", values)

print("\n封面数量:", len(audio.pictures))
for i, pic in enumerate(audio.pictures):
    print(i, pic.mime, pic.type, pic.width, pic.height, len(pic.data))