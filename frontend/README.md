# PyCompiler Studio

Tarayıcıda çalışan, bağımsız bir derleyici arayüzü ve küçük dil kütüphanesi.
Eğitim dilindeki programlar Python, JavaScript, C++, C# ve PHP kaynak koduna
dönüştürülebilir. Harici npm bağımlılığı veya derleme adımı gerekmez.

## Çalıştırma

Python 3 ve Node.js yüklü olmalıdır:

```powershell
cd frontend
npm run dev
```

Ardından `http://localhost:4173` adresini açın. Testleri çalıştırmak için:

```powershell
npm test
```

Derleyiciye `/app/` yolundan da ulaşılabilir; bu sayfa ana arayüze yönlendirir.

## Klasör yapısı

- `index.html`: editör, üretilen kod, konsol, denetim sonuçları ve örnek seçimi.
- `src/compiler.js`: tokenleştirici, ayrıştırıcı, Python kod üreticisi ve
  tarayıcı yorumlayıcısını dışarı açan dil kütüphanesi.
- `src/transpiler.js`: Python, JavaScript, C++, C# ve PHP çıktı üreticileri.
- `src/source-parser.js`: PyCompiler, Python, JavaScript, C++, C#, C, Java ve
  PHP kaynaklarının desteklenen alt kümelerini ortak AST'ye dönüştürür.
- `src/sql-validator.js`: SQL düzenleyicisinde istemci tarafı yapısal ön
  kontroller yapar; sorgu çalıştırmaz.
- `src/main.js`: editör etkileşimleri, hedef dil seçimi, kaynak kod üretimi,
  tarayıcıda çalıştırma ve dışa aktarma.
- `src/styles.css`: responsive arayüz stilleri.
- `test/compiler.test.js`: kütüphane için Node.js testleri.
- `test/transpiler.test.js`: hedef dil kod üretimi testleri.

## Kütüphane API'si

```js
import { compile, parse, run, tokenize } from "./src/compiler.js";
import { transpile } from "./src/transpiler.js";

const pythonSource = compile("let answer = 6 * 7\nprint(answer)");
const javascriptSource = transpile("let answer = 6 * 7\nprint(answer)", "javascript");
const result = run("let answer = 6 * 7\nprint(answer)");
```

`compile(source)` Python kaynak kodunu döndürür; `parse(source)` AST'yi,
`tokenize(source)` konum bilgili token'ları verir. `run(source)`, kullanıcı
kodunu JavaScript `eval`/`exec` olmadan AST üzerinden çalıştırır ve
`{ output, lines, variables, steps }` döndürür. Çalıştırma adımları varsayılan
olarak 100.000 ile sınırlıdır.

`transpile(source, target, sourceLanguage)` `python`, `javascript`, `cpp`,
`csharp` veya `php` hedeflerinden biri için kaynak metin üretir. Üçüncü
parametre varsayılan olarak `pycompiler` değerindedir. Girdi seçicisi
PyCompiler, Python, JavaScript, C++, C#, C, Java ve PHP için eğitim amaçlı
ortak bir sözdizimi alt kümesi sunar; tam dil derleyicisi değildir. Bu alt
kümeye atama, `print`/dil eşdeğerleri, `if/else`, `while`, temel ifadeler ve
desteklenen dillerin blokları dahildir. Python `for`, JavaScript `for`,
fonksiyonlar, sınıflar, harici kütüphaneler ve genel dil özellikleri
dönüştürülmez; desteklenmeyen sözdizimi hata verir. C/C++/C#/Java tam kaynak
dosyalarının yalnızca sınırlı `main`/`Program` sarmalayıcıları kabul edilir.

C++ ve C# değişkenleri sabit bir tipte kalmalıdır; sayı, metin ve boolean
atamaları arasında tür değiştirmek açık hata verir. HTML, CSS ve SQL kaynak
seçenekleri ayrı düzenleyicilerdir; dönüştürülmez veya çalıştırılmaz, yalnızca
seçilen dosya uzantısıyla dışa aktarılır. SQL için “SQL sorgusunu denetle”
eylemi boş sorgu, tanınan ifade başlangıcı, temel
`SELECT`/`INSERT`/`UPDATE`/`DELETE` yapısı, tırnak ve parantez dengesini
istemci tarafında kontrol eder. Bu tam bir SQL ayrıştırıcısı değildir; MySQL
veya başka bir veritabanına bağlanmaz ve sorgu yürütmez. HTML/CSS için compiler
doğrulaması yapılmaz. “Kodu denetle” eylemi desteklenen programlama dili
alt kümelerini mevcut transpiler üzerinden kontrol eder; hedef kodu çalıştırmaz.
Üretilen kod indirilip ilgili dilin kendi araç zinciriyle derlenmelidir:
uygulama native compiler barındırmaz ve hedef kodu çalıştırmaz. **Kaynağı
çalıştır** düğmesi, desteklenen kaynak alt kümesini PyCompiler AST
yorumlayıcısına aktararak tarayıcıda çalıştırır.

SQL, farklı bir sorgu dilidir; eğitim dilinden SQL'e dönüştürülmez. SQL
seçeneği sorgu yazıp `.sql` olarak dışa aktarmaya yarayan ayrı bir editördür;
sorgular uygulamada çalıştırılmaz. SQL denetimi yalnızca temel yapısal
kontrolleri kapsar; veritabanı bağlantısı, şema doğrulaması veya sorgu
yürütmesi içermez. Gerçek SQL çalıştırma için ayrıca bir backend API ve
güvenli veritabanı yapılandırması gerekir.

## Dil özellikleri

Değişken ataması (`let count = 3` veya `count = count + 1`), `print`,
aritmetik/karşılaştırma/mantıksal ifadeler, `if`/`else`, `while`, yorumlar
(`#`) ve noktalı virgül desteklenir. Bloklar süslü parantezle yazılır.
