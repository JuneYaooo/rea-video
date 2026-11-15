<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../docs/brand/logo-light.svg">
  <img src="../docs/brand/logo-dark.svg" width="400" alt="rea-video">
</picture>

Her videoyu tersine mühendislikle çöz.

Çekim çekim: gerçekten mi çekildi, yapay zekâyla mı üretildi, yoksa kodla mı yapıldı; ve nasıl yeniden yapılır.

Her çözümleme, ajanların katman katman okuduğu açık bir format olan **[VIDEO.md](https://videomd.github.io/videomd/)** ile yazılır.

[Web sitesi](https://www.reavideo.ai) | [中文](README_zh.md) | [English](../README.md) | [Русский](README_ru.md) | [日本語](README_ja.md) | [한국어](README_ko.md) | [Español](README_es.md) | [Português](README_pt.md) | [Français](README_fr.md) | [Deutsch](README_de.md) | [Tiếng Việt](README_vi.md) | [বাংলা](README_bn.md) | Türkçe

[![Stars](https://img.shields.io/github/stars/JuneYaooo/rea-video?style=flat)](https://github.com/JuneYaooo/rea-video/stargazers)
![Python](https://img.shields.io/badge/python-%E2%89%A53.10-blue)
![Agent](https://img.shields.io/badge/runs%20in-Claude%20Code%20%7C%20Codex-8A2BE2)
[![Output: VIDEO.md](https://img.shields.io/badge/output-VIDEO.md-3d4fd6)](https://videomd.github.io/videomd/)

<a href="https://trendshift.io/repositories/334878" target="_blank"><img src="https://trendshift.io/api/badge/trendshift/repositories/334878/daily" alt="JuneYaooo/rea-video | Trendshift" width="250" height="55"></a>

[![Visit our website](https://img.shields.io/badge/Visit%20our%20website-6644D8?style=for-the-badge)](https://www.reavideo.ai) [![Join our Discord](https://img.shields.io/badge/Join%20our%20Discord-5865F2?style=for-the-badge&logo=discord&logoColor=white)](https://discord.gg/dZj8D3GqWT) [![Follow on X](https://img.shields.io/badge/Follow%20%40yao__june12106-000000?style=for-the-badge&logo=x&logoColor=white)](https://x.com/yao_june12106)

⭐ *rea-video'yu daha çok kişinin bulmasına yardım et: bu repoya bir yıldız ver!*

<img src="../docs/cases/demo.gif" width="440" alt="Solda: telefonla çekilmiş orijinal TikTok videosu; sağda: başka bir ürünle yapılmış yapay zekâ versiyonu">

Solda telefonla çekilmiş bir TikTok reklamı var. Sağda başka bir ürünle yapılmış yapay zekâ versiyonu. rea-video'nun kararı: soldaki tamamen gerçek çekim, tek mekân ve iki kamera konumu; sağdaki tamamen yapay zekâ, 3 üretimde 8 çekim.

</div>

## Hızlı başlangıç

rea-video yapay zekâ ajanları için yapıldı. Claude Code, Codex ya da komut çalıştırabilen herhangi bir ajana şunu söyle:

```text
Install https://github.com/JuneYaooo/rea-video, then break down this video: /path/to/video.mp4
```

Ajan CLI'ı kurar, iş akışını öğrenir ve her şeyi baştan sona çalıştırır. ffmpeg ve Python 3.10+ gerekir.

Çözümlemeler tamamen yenilendi. Her biri sana iki çıktı verir:

- **Rapor** (`report.html` / PDF), senin için: okuması daha kolay, yapısı daha net; videonun nasıl yapıldığını ve nasıl yeniden yapılacağını öğrenmek ve anlamak daha kolay.
- **[VIDEO.md](https://videomd.github.io/videomd/)**, yapay zekân için: katmanlıdır, böylece yapay zekâ yalnızca bir sorunun ihtiyaç duyduğu kısmı okur ve daha az token harcar.

Ajana uç noktasını (endpoint) ve anahtarını vererek video anlayabilen bir model de bağlayabilirsin (Gemini ya da Doubao olur). Bu, gerçek çekim / yapay zekâ / 3D kararlarını daha isabetli yapar ve her çekim için tersine mühendislikle çıkarılmış bir istem (prompt) ekler. Model olmadan da iyi çalışır; ajanın görüntü görebiliyorsa emin olunamayan çekimleri kendisi kontrol eder.

> Raporlar hangi dilde sorduysan o dilde yazılır (Çince ya da İngilizce). Aşağıdaki örnek raporlar İngilizcedir.

## Neleri çözümleyebilir

| Video türü | Örnekler | Ne elde edersin |
|---|---|---|
| Gerçek çekim | Kameraya konuşma, masaüstü çekim, elde ürün tanıtımı, vlog, mağaza ziyareti | Mekânlar ve kamera konumları, kadraj, kamera hareketleri, ışık (ekipman listeleriyle 12 kurulum), renk düzenleme |
| Yapay zekâ videosu | Metinden/görselden videoya, yapay zekâ kısa dizisi, yapay zekâ müzik videosu | Kanıtlar, her çekim için tersine mühendislikle çıkarılmış istem, üretimlere nasıl bölüneceği ve hangi modelin kullanılacağı |
| Avatar | Sesle hareket ettirilen portre, dudak senkronu | Hangi çekimlerin avatar çekimi olduğu, hangi portre ve sesin gerektiği |
| 3D / animasyon | Blender / C4D anlatım videoları, ürün animasyonu, 2D animasyon, stop-motion | Video modeliyle mi üretilmeli, yoksa 3D kodla mı render edilmeli |
| Kod / şablon | Kinetik tipografi, arayüz demoları, grafikler, slayt tarzı kartlar | Metin, yerleşim ve hareket zamanlaması; Remotion projesi olarak yeniden kurmaya hazır |
| Ekran kaydı | Yazılım eğitimleri, web demoları | Hangi kısımların senin kendin kaydetmen gereken gerçek materyal olduğu |
| Karma / kurgu | Yapay zekâ karakterler + kodla yapılmış arayüz + gerçek ekran kaydı; yapay zekâ düzenlemeli gerçek çekim | Her çekim ayrı değerlendirilir, sonra orijinal zaman çizelgesinde yeniden birleştirilir |

Görüntülerin nasıl yapıldığının yanı sıra her çözümleme şunları da kapsar:

- Altyazılar ve stilli metinler: her satırın başlangıcı ve bitişi (SRT / ASS olarak dışa aktarılır), ayrıca rengi, dış çizgisi ve metnin nasıl girdiği
- Çıkartmalar, emojiler, resim içinde resim: nerede durdukları ve ne kadar kaldıkları
- Kurgu: kesmelerin nerede olduğu, ne kadar hızlı oldukları, ritme oturup oturmadıkları
- Ses: insan mı yapay zekâ sesi mi, yapay zekâ müziği mi kütüphane müziği mi ve BPM'i, her ses efektinin nereye düştüğü
- Kendin sağlaman gereken materyal: ekran kayıtları, ekran görüntüleri, ürün fotoğrafları

## Örnekler

`docs/cases/videos/` içindeki örnek videolar repoyu küçük tutmak için yeniden sıkıştırıldı; bu da TikTok / Douyin platform etiketlerini siliyor. Bu yüzden onları kendin çalıştırırsan, özellikle görme modeli olmadan, aşağıdaki raporlardan farklı sonuçlar alırsın. Sonuçları tekrarlamak için platformdan indirilmiş orijinal dosyaları kullan.

<table>
<tr>
<td width="50%" valign="top">
<a href="../docs/cases.md#2-混合片ai-人物对话--代码界面--真实录屏"><img src="../docs/cases/dual_role/thumb.jpg"></a><br>
<b>Karma klip</b> · 19 sn · 10 çekim<br>
Konuşan yapay zekâ karakterler + kodla yapılmış arayüz + 8 sn gerçek ekran kaydı. 5 diyalog çekimi arayüz bölümleriyle bölünüyor ama aynı mekânı paylaşıyor, bu yüzden tek bir üretim hepsini kapsıyor.<br>
<a href="../docs/cases/videos/dual_role.mp4">Video</a> · <a href="../docs/cases/dual_role/report_en.md">Rapor</a>
</td>
<td width="50%" valign="top">
<a href="../docs/cases.md#3-3d-科普片咸鸭蛋为什么会流油"><img src="../docs/cases/salted_egg/thumb.jpg"></a><br>
<b>3D anlatım videosu</b> · 67 sn · 21 çekim<br>
Tamamı 3D, yapay zekâ seslendirmesi. 10 video üretimiyle yapabilir ya da bir LLM'e Blender / Three.js kodu yazdırabilirsin.<br>
<a href="../docs/cases/videos/salted_egg.mp4">Video</a> · <a href="../docs/cases/salted_egg/report_en.md">Rapor</a>
</td>
</tr>
<tr>
<td width="50%" valign="top">
<a href="../docs/cases.md#4-代码-ui-动效产品宣传片"><img src="../docs/cases/v10/thumb.jpg"></a><br>
<b>Ürün tanıtımı</b> · 70 sn · 12 çekim<br>
%83 kodla yapılmış hareketli grafik, %12 ekran kaydı. Video modeline gerek yok; tek bir Remotion projesi yeter.<br>
<a href="../docs/cases/videos/v10_oiioii_gen_coding_first.mp4">Video</a> · <a href="../docs/cases/v10/report_en.md">Rapor</a>
</td>
<td width="50%" valign="top">
<a href="../docs/cases.md#5-ai-音乐-mv歌是-ai-写的还是曲库的"><img src="../docs/cases/qing_mv/thumb.jpg"></a><br>
<b>Yapay zekâ müzik videosu</b> · 165 sn · 86 çekim<br>
Şarkının yapay zekâyla üretildiğini doğru tespit ediyor (Suno ile yapılmış). Görme modeli bazı çekimlere "gerçek çekim dram" dedi; ajan bir parşömendeki sahte Çince karakterleri fark etti ve onları yapay zekâ olarak işaretledi.<br>
<a href="../docs/cases/videos/qing_mv.mp4">Video</a> · <a href="../docs/cases/qing_mv/report_en.md">Rapor</a>
</td>
</tr>
<tr>
<td width="50%" valign="top">
<a href="../docs/cases.md#6-实拍带货沉浸式开箱"><img src="../docs/cases/unboxing/thumb.jpg"></a><br>
<b>Gerçek çekim kutu açılışı</b> · 72 sn · 29 çekim<br>
Tamamı gerçek çekim: tepeden bakan bir telefon düzeneği, tek bir halı, tek kamera konumu, dış ses yok, ortam sesi artı kütüphane fon müziği. Platformun yeniden kodlamasından sonra çevrimdışı araçlar videonun %35'ine yapay zekâ dedi; ajanın incelemesinden sonra %97 gerçek çekim çıktı.<br>
<a href="../docs/cases/videos/unboxing.mp4">Video</a> · <a href="../docs/cases/unboxing/report_en.md">Rapor</a>
</td>
</tr>
</table>

## Yeniden yapımlar

rea-video bir videoyu çözümledikten sonra [capsule-cinema](https://github.com/JuneYaooo/capsule-cinema) içindeki yeniden yapım tarifi; orijinalin kamerasını, hareketini, temposunu ve geçişlerini koruyup yalnızca seçtiğin öğeleri değiştiren yeni bir versiyon üretir.
Bunlar kendi sunucumuzda çalışan bir MiniMax H3 ile yapıldı: hareket referansı olarak orijinal çekim, görünüm için de öğeleri değiştirilmiş ana kareler (gpt-image-2) kullanıldı.
Aşağıda OiiOii'nin WeChat makalelerinde gösterdiği üç yeniden yapım var. Her birinin iki versiyonunu yaptık: biri OiiOii ile aynı değişiklikle, diğeri ayrıca konuyu, mekânı ve aksesuarları da değiştirerek.
Her GIF dört versiyonu senkronize oynatır: orijinal, OiiOii'nin yeniden yapımı, bizim yeniden yapımımız ve öğe değiştirilmiş versiyon.

<table>
<tr><td>
<b>Tepeden kıyafet değişimi</b> · 12 sn<br>
Aynı değişiklik: kadın → erkek, üç kıyafet → uyumlu erkek kıyafetleri. Öğe değişikliği: Çin tarzı bir çalışma odasında üç tarihî Hanfu kıyafeti giyen bir kız; kumanda yuvarlak bir yelpazeye dönüşüyor.<br>
<img src="../docs/cases/remake/outfit.gif"><br>
<a href="../docs/cases/remake/outfit_compare.mp4">HD karşılaştırma videosu (sesli)</a> · <a href="../docs/cases/remake/outfit_sheet.jpg">aynı andaki kareler</a>
</td></tr>
<tr><td>
<b>Kâğıt işi / suluboya animasyon</b> · 30 sn<br>
Aynı değişiklik: başrolde yeni bir kil kız. Öğe değişikliği: bir tilki; orman → mercan resifi, bulutlar → yıldızlı gökyüzü, gün batımı → kutup ışıkları.<br>
<img src="../docs/cases/remake/paper.gif"><br>
<a href="../docs/cases/remake/paper_compare.mp4">HD karşılaştırma videosu (sesli)</a> · <a href="../docs/cases/remake/paper_sheet.jpg">aynı andaki kareler</a>
</td></tr>
<tr><td>
<b>Elde ürün videosu</b> · 21 sn · 11 çekim<br>
Aynı değişiklik: özgün yeni bir ürün, İngilizce çıkartma → Çince altyazı. Öğe değişikliği: pembe ürün, mutfak → kamp masası, yeni malzemeler.<br>
<img src="../docs/cases/remake/juicer.gif"><br>
<a href="../docs/cases/remake/juicer_compare.mp4">HD karşılaştırma videosu (sesli)</a> · <a href="../docs/cases/remake/juicer_sheet.jpg">aynı andaki kareler</a>
</td></tr>
</table>

HD karşılaştırma videoları orijinal sesi kullanır. Orijinaller ve OiiOii versiyonları makalelerden alınmıştır ve yalnızca karşılaştırma amacıyla gösterilmektedir.

Yeniden yapımı barındırılan bir yapay zekâ video editörü olan [ChatCut](https://chatcut.io/r/github-e4rd) ile de yapabilirsin: kurulacak model yok ve üretilen çekimler düzenlemeye devam edebileceğin bir zaman çizelgesine yerleşir. <sub>Sponsor</sub>

## Sponsorlar

rea-video ücretsiz ve açık kaynaktır. Sponsorlar bakımının sürmesine yardım ediyor.

<table><tr>
<td align="center" width="200"><a href="https://chatcut.io/r/github-e4rd"><picture>
  <source media="(prefers-color-scheme: dark)" srcset="../docs/brand/chatcut-logo-light.svg">
  <img src="../docs/brand/chatcut-logo-dark.svg" height="32" alt="ChatCut">
</picture></a></td>
<td><b><a href="https://chatcut.io/r/github-e4rd">ChatCut</a></b>, Claude Code ve Codex için çekimleri üreten, onları bir zaman çizelgesinde kurgulayan ve bitmiş videoyu dışa aktaran bir yapay zekâ video editörüdür.<br>
<a href="https://chatcut.io/r/github-e4rd">ChatCut'ı ücretsiz dene</a></td>
</tr></table>

<sub>Sponsorlu · <a href="https://reavideo.ai/en/contact/">Sponsor ol</a></sub>

## Doğruluk

"Nasıl yapıldı" kararının çekim süresine göre ağırlıklandırılmış doğruluğu:

| | Ayar kümesi (15) | Ayrılmış küme (16) | Yeniden kodlanmış WeChat videoları (10) |
|---|---|---|---|
| Yalnızca araçlar (çevrimdışı, ücretsiz) | %98,3 | %99,6 / %98,9 | %88,6 |
| + görme modeli (Gemini) | — | %99,6 / %99,8 | %99,6 |
| + ajanın görsel incelemesi | — | %99,6 / %99,8 | %100 |

Ayrılmış küme sütununda iki sayı var: holdout (9 video) ve holdout2 (7 video).

Orijinal dosyalarda genellikle araçlar tek başına yeter. Platformlardan indirilen videolar yeniden sıkıştırılmıştır ve bu, gürültü kanıtını siler; bu yüzden %99'un üzerine tekrar çıkmak için görsel bir kontrol gerekir.

Gerçek materyal tespiti %97–99; elle etiketlenmiş dokuz klipte çekim sınırları %95 duyarlılık (recall) ve %94 kesinliğe (precision) ulaşıyor. Sayılar ve nasıl tekrarlanacakları: [eval/RESULTS.md](../eval/RESULTS.md).

## Nasıl çalışır

![rea-video iş akışı](../docs/rea-flow_en.svg)

1. Ayır: videoyu çekimlere böl ve sesi konuşma, müzik ve efektler olarak ayır.
2. Kanıt topla: ölç (kare temposu, sensör gürültüsü, görüntünün tamamının tek bir düz düzlem gibi hareket edip etmediği, meta verideki AIGC etiketleri), bak (eller, yazılar, fizik) ve dinle (BPM, ton, şarkı mı konuşma mı).
3. Karar ver: AIGC etiketleri ve kare temposu gibi sağlam kanıtlar "öyle görünüyor"dan üstündür. Çelişkiler, ajanın görsel olarak kontrol etmesi için işaretlenir.
4. Yeniden yapımı planla: çekimleri hedef video modelinin gerçekten yapabildiklerine göre grupla; en uzun klip süresi, çoklu çekim desteği ve kaç referans görsel aldığı gibi.

## Yıldız geçmişi

[![Star History Chart](https://api.star-history.com/svg?repos=JuneYaooo/rea-video&type=Date)](https://star-history.com/#JuneYaooo/rea-video&Date)

## SSS

<details>
<summary>Hypit gibi tek tıkla yeniden yapım araçlarından farkı ne?</summary>

[Hypit](https://github.com/hypit-ai/hypit) bir referans video alır ve yenisini yapar: ajan orijinali anlamak için kare ızgaralarını okur, desteklediği modellerle (Seedance, PixVerse, MiniMax, Wan ve diğerleri) görüntü üretir, altyazıları ve hareketli grafikleri HTML ile render eder.

Orijinalin nasıl yapıldığını sormaz. Gerçek çekim bir kaynak da aynı akıştan geçer; kaç kamera kullanıldığını ya da nasıl ışıklandırıldığını söylemez. Hangi yapay zekâ videolarını yakalayabildiği desteklediği modellere bağlıdır: Kling ya da Veo yok, ayrı bir avatar ya da 3D yolu yok, yapay zekâ müziği yok (kendin getirirsin). En güçlü olduğu alan bir senaryoyu izleyen kameraya konuşma, podcast ve röportaj videoları; müziğe dayalı kurgularda, ürün hareketli grafiklerinde ve sinematik kısa filmlerde daha zayıf.

rea-video video render etmez. Çekim çekim bir şeyin çekildiğini mi, yapay zekâyla mı üretildiğini mi, kodla mı yapıldığını mı bulur, sonra her biri için bir çekim planı, istemler ya da bir kod yaklaşımı verir. Hızlıca benzerini yapmak için Hypit daha hızlıdır. Orijinalin nasıl yapıldığını anlamak ve onu ucuza yeniden yapmak için rea-video'yu kullan. İkisi birlikte de rahatça çalışır.

</details>

<details>
<summary>Video anlayabilen bir modele ihtiyacım var mı? Maliyeti ne?</summary>

Hayır. Yalnızca araçlar modu çevrimdışı ve ücretsizdir, orijinal dosyalarda zaten isabetlidir. Platformlardan indirilip yeniden sıkıştırılmış videolar için video anlayabilen bir model ekle (Gemini ya da Doubao olur) ya da görüntü görebilen bir ajan kullan; o servis ne ücret alıyorsa onu ödersin. Otomatik video üretimi (capsule-cinema) önce ücretsiz bir deneme (dry run) yapar ve ücretli modelleri ancak sen onayladıktan sonra çağırır.

</details>

<details>
<summary>Videonun tamamını otomatik olarak yeniden yapabilir mi?</summary>

Kısmen. [capsule-cinema](https://github.com/JuneYaooo/capsule-cinema) kuruluysa yapay zekâ çekimleri üretilir ve orijinal zaman çizelgesine otomatik olarak geri yerleştirilir. Gerçek çekimleri çekim planına göre sen çekersin, kod çekimlerini de ajan Remotion projesi olarak yazar. Bkz. [docs/replicate.md](../docs/replicate.md).

</details>

<details>
<summary>Çok bölümlü bir kısa diziyi çözümleyebilir mi?</summary>

rea-video bir seferde tek bir video üzerinde çalışır. Süren bir hikâyesi olan çok bölümlü kısa diziler için [rea-toon](https://github.com/JuneYaooo/rea-toon)'a bak.

</details>

<details>
<summary>VIDEO.md nedir ve rea-video neden bir tane yazıyor?</summary>

Her becerinin (skill) bir `SKILL.md`'si vardır; her videonun da bir `VIDEO.md`'si olur. Bu, video çözümlemeleri için, modellerin yalnızca bir sorunun ihtiyaç duyduğu kısmı okuması için yapılmış açık bir formattır. Tam bir çözümleme yüz binlerce token tutar; VIDEO.md bunu seviyelere ayırır: birkaç yüz token'lık bir kart, bir genel bakış ve harita, çekim başına bir satır olan bir zaman çizelgesi, sonra çekim başına bir dosya. Her dosya kendi boyutunu belirtir ve ekranda görülen, araçların çıkardığı sonuçlardan ayrı tutulur.

rea-video her çıktı klasörüne bir tane yazar (`out/ref/VIDEO.md`) ve agent becerisi ham veri yerine onu okur. Diğer ajanlar ve araçlar rea-video'yu bilmeden onu okuyabilir: `pip install videomd`, ardından `videomd check out/ref`. Spesifikasyon ve rehberler [videomd.github.io/videomd](https://videomd.github.io/videomd/) adresinde.

</details>

<details>
<summary>Başkasının videosunu doğrudan yeniden paylaşabilir miyim?</summary>

Hayır. rea-video bir videonun yapısını, temposunu ve tekniklerini öğrenmek, sonra onu hakkına sahip olduğun materyalle yeniden yapmak içindir. Başkalarının görüntülerini, müziğini, karakterlerini ya da suretini yeniden kullanma. Yayınlarken platform kurallarına ve yerel yapay zekâ içeriği etiketleme gerekliliklerine uy.

</details>

## Belgeler

- [docs/what-it-detects.md](../docs/what-it-detects.md): tespit ettiği her şey (10 görsel tür, kamera, ışık, renk, ses)
- [docs/replicate.md](../docs/replicate.md): rapordan yeniden yapım nasıl yapılır
- [docs/cases.md](../docs/cases.md): her örneğin ayrıntıları
- [docs/decompose.md](../docs/decompose.md): tespit kuralları
- [docs/cli.md](../docs/cli.md): CLI kullanımı ve capsule-cinema entegrasyonu
- [docs/videomd.md](../docs/videomd.md): ajanların ve sonraki araçların okuduğu standart çözümleme paketi VIDEO.md (açık format: [videomd/videomd](https://github.com/videomd/videomd))
- [rea_video/capabilities/](../rea_video/capabilities/README.md): yeniden yapım planı için model seçmekte kullanılan video / görsel / ses modeli yetenek tabloları
- [eval/RESULTS.md](../eval/RESULTS.md): değerlendirme sonuçları

Belgeler şimdilik Çince.

## Topluluk

Sorular, çözümlemeler ve yeniden yapım fikirleri: [GitHub Discussions](https://github.com/JuneYaooo/rea-video/discussions). [Discord](https://discord.gg/dZj8D3GqWT)'da bizimle sohbet et. Çince konuşanlar bizi [linux.do](https://linux.do/)'da da bulabilir.

Bir videonun çözümlenmesini mi istiyorsun? Bağlantısıyla bir [istek issue'su](https://github.com/JuneYaooo/rea-video/issues/new?template=request_breakdown.yml) aç; sonucu bir örnek olarak yayınlayalım.

## Teşekkürler

[REA (Reverse Engineer Anything)](https://github.com/morluto/rea)'dan ilham alındı: gördüğünden nasıl yapıldığına geri doğru çalış, her iddiayı kanıtla destekle ve ölçerek doğrula.

Ses ayırma; konuşma ve müzik için [UVR MDX-Net](https://github.com/TRvlvr/model_repo), ses efektleri için [BandIt v2](https://github.com/kwatcharasupat/bandit-v2) (Watcharasupat, Wu ve Orife; ağırlıklar CC BY-SA 4.0) kullanır. İki model de ilk kullanımda indirilir ve bu reponun parçası değildir.
