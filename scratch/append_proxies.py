import csv
import io
import os

csv_data = """ip,anonymityLevel,asn,country,isp,latency,org,port,protocols,speed,upTime,upTimeSuccessCount,upTimeTryCount,updated_at,responseTime
"61.9.32.30","elite","AS17970","PH","Sky Cable Corporation","252","Sky Cable Corporation","58765","socks5","1017","97","37","38","2026-07-12T01:17:25.020Z","227"
"79.76.121.87","transparent","AS31898","DE","Oracle Corporation","7","Oracle Cloud Infrastructure (eu-frankfurt-1)","3128","http","9","76","64","84","2026-07-12T01:23:50.915Z","233"
"212.220.84.69","elite","AS12389","RU","Rostelecom networks","73","Dynamic distribution IPs for broadband services","1080","socks5","2877","100","46","46","2026-07-12T01:20:36.933Z","239"
"194.154.25.145","transparent","AS48040","SE","Fornex Hosting S.L.","23","FORNEX","8081","https","356","100","60","60","2026-07-12T01:24:46.729Z","241"
"27.254.99.183","elite","AS9891","TH","CS Loxinfo Public Company Limited","196","N/A","8118","http","1291","100","89","89","2026-07-12T01:03:40.630Z","243"
"181.78.51.157","transparent","AS52468","GT","Ufinet Panama S.A.","151","UFINET Guatemala S. A","999","https","5005","100","41","41","2026-07-12T01:16:15.710Z","252"
"45.232.152.2","transparent","AS266761","AR","Vicente Claudio Orlando","245","Vicente Claudio Orlando","8080","http","1086","98","92","94","2026-07-12T01:14:50.111Z","255"
"138.2.127.197","elite","AS31898","KR","Oracle Corporation","264","Oracle Cloud Infrastructure (ap-chuncheon-1)","3128","http","5086","80","24","30","2026-07-12T01:44:49.900Z","255"
"103.72.101.61","transparent","AS44259","IN","Ultahost, Inc.","126","N/A","3128","https","895","83","5","6","2026-07-12T01:09:53.224Z","272"
"178.165.42.166","elite","AS34700","UA","Maxnet Ltd","40","Maxnet Ltd.","3128","http","1892","100","92","92","2026-07-12T01:22:39.729Z","273"
"81.90.29.194","elite","AS215540","NL","Global Connectivity Solutions LLP","24","Global Connectivity Solutions LLP","10808","socks4","5700","95","89","94","2026-07-12T01:07:39.226Z","277"
"47.86.42.224","elite","AS45102","HK","Alibaba Cloud LLC","181","Alibaba Cloud - HK","1011","socks5","6979","100","73","73","2026-07-12T01:44:38.416Z","282"
"138.124.26.19","elite","AS210644","SE","Aeza International LTD","42","Aeza Group LLC","1080","socks4","5002","98","93","95","2026-07-12T01:32:55.439Z","285"
"94.103.13.179","elite","AS202696","RU","Trusted Network LLC","44","Trusted Network LLC","40001","socks4","98","100","1","1","2026-07-12T01:44:30.340Z","289"
"27.147.131.122","transparent","AS23688","BD","Link3 Technologies Limited","189","Corporate Subscriber","8090","https","1144","97","91","94","2026-07-12T01:44:12.632Z","292"
"72.223.188.67","elite","AS22773","US","Cox Communications Inc.","153","Cox Communications Inc.","4145","socks5","5001","78","36","46","2026-07-12T01:31:30.974Z","292"
"180.191.231.19","transparent","AS4775","PH","Globe Telecom","204","N/A","8082","https","871","100","94","94","2026-07-12T01:24:33.529Z","293"
"165.16.192.205","elite","AS327792","TZ","CSS","176","N/A","1080","socks5","9018","100","33","33","2026-07-12T01:09:35.318Z","294"
"185.140.209.75","elite","AS56630","NL","Melbikomas UAB","14","Melbikomas UAB","40001","socks5","533","100","9","9","2026-07-12T01:42:21.346Z","296"
"170.82.194.134","anonymous","AS266446","BR","Itjsc Servicos De Comunicacao E Solucoes Ltda","207","Rio Branco Comercio e Industria de Papeis Ltda","3128","https","5001","100","52","52","2026-07-12T01:02:43.521Z","299"
"49.148.137.214","transparent","AS9299","PH","Philippine Long Distance Telephone Co.","225","Philippine Long Distance Telephone Company","8082","http","924","100","14","14","2026-07-12T01:42:48.011Z","301"
"1.179.172.45","elite","AS131293","TH","TOT Public Company Limited","178","TOT Public Company Limited","31225","socks4","381","94","89","95","2026-07-12T01:45:35.940Z","303"
"37.120.189.175","elite","AS197540","DE","netcup GmbH","6","netcup GmbH","1080","socks5","5001","96","50","52","2026-07-12T01:06:37.819Z","305"
"193.58.147.148","elite","AS25693","US","Virtual Machine Solutions LLC","132","Virtual Machine Solutions LLC","8118","http","136","100","14","14","2026-07-12T01:07:54.624Z","309"
"213.25.70.1","elite","AS5617","PL","Orange Polska Spolka Akcyjna","25","Przedsiebiorstwo Telekomunikacyjno Informatyczne NetCom Marcin Biegaj","3629","socks4","5001","99","88","89","2026-07-12T01:45:36.731Z","310"
"36.92.140.113","transparent","AS7713","ID","PT. Telekomunikasi Indonesia","180","Telekomunikasi Indonesia","8080","http","5001","100","36","36","2026-07-12T01:15:45.618Z","312"
"209.38.214.48","elite","AS14061","DE","DigitalOcean, LLC","8","Digital Ocean","1080","socks5","26","91","86","94","2026-07-12T01:31:09.036Z","315"
"113.176.118.150","elite","AS45899","VN","VNPT","202","Vietnam Posts and Telecommunications Group","1080","socks5","6721","100","92","92","2026-07-12T01:27:25.628Z","315"
"124.105.79.237","transparent","AS9299","PH","Philippine Long Distance Telephone Co.","270","Philippine Long Distance Telephone Company","8080","https","1108","95","74","78","2026-07-12T01:21:58.942Z","315"
"191.102.107.237","transparent","AS262186","CO","TV AZTECA SUCURSAL COLOMBIA","172","Centro Soluciones Servicios Rapidhardwar","999","http","5002","100","76","76","2026-07-12T01:10:03.808Z","319"
"45.40.136.39","elite","AS398101","US","GoDaddy.com, LLC","157","GoDaddy.com, LLC","45741","socks5","5003","100","65","65","2026-07-12T01:30:53.437Z","320"
"200.227.89.50","anonymous","AS4230","BR","Claro S.A","165","Rio Branco Comercio e Industria de Papeis Ltda","3128","https","5002","100","46","46","2026-07-12T01:43:36.218Z","322"
"103.83.86.222","transparent","AS44382","TR","Fiba Cloud Operation Company, LLC","44","White Label","3128","http","5001","100","22","22","2026-07-12T01:14:58.624Z","322"
"95.182.78.10","elite","AS50648","UA","PE UAinet","45","PE UAinet","5678","socks4","13417","100","89","89","2026-07-12T01:25:25.737Z","323"
"46.8.112.212","elite","AS215305","NL","Mastersoft S.R.L.","50","Mastersoft S.R.L","1080","socks4","392","99","85","86","2026-07-12T01:09:42.320Z","323"
"154.113.209.162","transparent","AS37282","NG","Main one Cable Company Nigeria Limited","104","N/A","8082","http","766","100","94","94","2026-07-12T01:32:49.614Z","324"
"90.188.92.116","elite","AS12389","RU","Rostelecom networks","90","OJSC Sibirtelecom","36335","socks4","5002","100","44","44","2026-07-12T01:02:40.928Z","324"
"125.227.45.188","elite","AS3462","TW","Chunghwa Telecom Co., Ltd.","248","Chunghwa Telecom Co. Ltd.","5001","socks5","4974","74","68","92","2026-07-12T01:30:07.514Z","325"
"111.79.111.126","transparent","AS149837","CN","China Telecom","274","Chinanet JX","3128","https","5001","96","50","52","2026-07-12T01:11:37.329Z","325"
"27.49.68.66","transparent","AS17639","PH","Converge ICT","260","N/A","9999","https","5001","97","35","36","2026-07-12T01:03:34.514Z","325"
"96.9.88.130","elite","AS131207","KH","S.I Group","201","N/A","4153","socks4","2262","100","49","49","2026-07-12T01:44:27.826Z","326"
"65.109.219.73","elite","AS24940","FI","Hetzner Online GmbH","30","Hetzner Online GmbH","1080","socks4","119","100","38","38","2026-07-12T01:09:10.220Z","329"
"14.34.180.21","elite","AS4766","KR","Korea Telecom","298","Kornet","38157","https","2561","100","9","9","2026-07-12T01:24:53.631Z","331"
"168.243.77.190","transparent","AS271968","DO","CENTRIC MOBILITY (CEMO), S.R.L","129","CENTRIC MOBILITY CEMO, S.R.L","999","http","532","98","84","86","2026-07-12T01:07:06.114Z","335"
"206.123.156.233","elite","AS213790","GB","Limited Network LTD","14","Secure Internet LLC","9965","socks5","72","95","77","81","2026-07-12T01:04:57.327Z","335"
"198.13.63.73","elite","AS20473","JP","The Constant Company","286","Vultr Holdings, LLC","1080","socks4","5001","100","52","52","2026-07-12T01:40:42.741Z","341"
"185.157.111.3","elite","AS202652","EE","SkyLive Telecom ldt","35","Elevi","5678","socks4","2852","100","52","52","2026-07-12T01:45:20.684Z","347"
"197.232.23.40","transparent","AS36866","KE","Jamii Telecommunications Limited","190","Faiba Enterprise3","8080","https","1897","100","25","25","2026-07-12T01:10:29.316Z","349"
"123.253.137.173","transparent","AS17639","PH","ComClark Network & Technology Corp","249","Converge ICT Network","8082","http","1003","83","10","12","2026-07-12T01:44:31.036Z","350"
"68.71.243.14","elite","AS46562","US","Performive LLC","167","ZeroLag Communications","4145","socks4","5001","98","48","49","2026-07-12T01:15:36.634Z","352"
"186.227.196.104","transparent","AS53055","BR","Dimenoc Servicos De Informatica Ltda","187","HostDime","3128","https","906","100","52","52","2026-07-12T01:40:04.216Z","353"
"47.250.115.134","elite","AS45102","MY","Alibaba Cloud LLC","162","Alibaba Cloud - MY","1080","socks5","324","98","51","52","2026-07-12T01:07:36.018Z","358"
"113.249.101.123","elite","AS134420","CN","Chongqing Telecom","300","Chinanet CQ","18255","https","5001","80","20","25","2026-07-12T01:30:31.108Z","382"
"195.114.7.6","elite","AS41161","RU","Artem Zubkov","91","Artem Zubkov","1080","socks5","20626","88","81","92","2026-07-12T01:37:02.214Z","385"
"84.241.29.213","elite","AS31549","IR","SHATEL Network","86","Shatel Group","8080","https","5001","94","16","17","2026-07-12T01:09:42.314Z","388"
"197.155.73.230","elite","AS30844","KE","Liquid Telecommunications Ltd","211","Tribe","1080","socks4","862","100","20","20","2026-07-12T01:45:23.649Z","389"
"168.119.153.216","elite","AS24940","DE","Hetzner Online GmbH","13","Hetzner Online GmbH","8888","https","25","100","46","46","2026-07-12T01:32:38.238Z","390"
"213.148.6.12","elite","AS48988","KZ","Modern Server Solutions LLP","104","Modern Server Solutions LLP","7777","socks5","410","100","92","92","2026-07-12T01:16:39.827Z","391"
"87.251.74.124","transparent","AS215881","RU","Elytrium LLC","129","Elytrium LLC","3128","https","3742","100","12","12","2026-07-12T01:12:55.537Z","393"
"174.77.111.198","elite","AS22773","US","Cox Communications Inc.","156","Cox Communications","49547","socks5","5000","84","41","49","2026-07-12T01:05:13.037Z","394"
"98.188.47.150","elite","AS22773","US","Cox Communications Inc.","165","Cox Communications","4145","socks4","5002","83","43","52","2026-07-12T01:41:53.415Z","395"
"183.90.187.248","elite","AS400619","HK","Arosscloud Sdn. BHD","223","N/A","9050","socks4","231","100","78","78","2026-07-12T01:05:32.538Z","402"
"177.128.81.10","elite","AS262365","BR","IBI TELECOM EIRELI","218","Fernando Markson Brito - - ME","81","socks4","895","98","40","41","2026-07-12T01:04:49.042Z","404"
"61.152.125.234","elite","AS4812","CN","China Telecom (Group)","250","Shanghai Data Solution Co.","9300","https","5001","88","22","25","2026-07-12T01:35:57.918Z","407"
"200.34.227.28","transparent","AS28343","BR","UNIFIQUE TELECOMUNICACOES S/A","210","UNIFIQUE TELECOMUNICACOES S/A","8080","http","1172","99","80","81","2026-07-12T01:23:09.514Z","408"
"91.243.195.9","elite","AS15377","UA","Traditional LLC","53","Intellect Dnepr Telecom LLC","35860","socks5","318","100","94","94","2026-07-12T01:04:57.327Z","411"
"46.197.136.14","transparent","AS47524","TR","Turksat Internet Services","97","Turksat Services","8080","http","281","100","94","94","2026-07-12T01:09:42.315Z","413"
"119.148.20.109","elite","AS23923","BD","Agni Systems Ltd. SUB","168","Agni Systems Ltd.","22122","socks5","5001","94","49","52","2026-07-12T01:02:05.313Z","416"
"103.194.88.226","elite","AS134319","IN","Elyzium Technologies Pvt. Ltd.","199","Elyzium Technologies Pvt. Ltd.","1080","socks4","2613","99","93","94","2026-07-12T01:19:40.722Z","417"
"103.70.44.6","transparent","AS45804","IN","Meghbela Cable & Broadband Services (P) Ltd","188","Aditya Broadband Services Pvt Ltd","8080","http","357","100","81","81","2026-07-12T01:44:17.335Z","417"
"211.197.173.196","transparent","AS4766","KR","Korea Telecom","272","N/A","3064","https","567","100","36","36","2026-07-12T01:31:52.221Z","417"
"212.46.242.185","elite","AS3216","RU","SOVINTEL/END broadband internet","53","N/A","1080","socks4","5001","100","30","30","2026-07-12T01:45:15.241Z","417"
"38.194.250.66","transparent","AS28458","MX","IENTC S de RL de CV","172","IENTC S de RL de CV","999","http","1075","96","81","84","2026-07-12T01:04:59.816Z","421"
"163.227.250.58","transparent","AS153889","ID","PT Media Central Access","173","PT Media Central Access","8080","http","690","100","65","65","2026-07-12T01:44:09.428Z","422"
"65.21.194.253","elite","AS24940","FI","Hetzner Online GmbH","33","Hetzner","9050","socks4","199","100","78","78","2026-07-12T01:36:46.820Z","426"
"58.69.124.137","transparent","AS9299","PH","Philippine Long Distance Telephone Co.","211","Philippine Long Distance Telephone Company","8080","https","890","94","34","36","2026-07-12T01:13:23.821Z","429"
"94.54.82.4","elite","AS47524","TR","Turksat Internet Services","61","N/A","9050","socks5","245","99","77","78","2026-07-12T01:29:33.017Z","433"
"185.166.24.221","transparent","AS207097","IQ","Online Company Ltd","89","N/A","1976","http","386","98","90","92","2026-07-12T01:44:16.345Z","434"
"61.191.119.134","elite","AS4134","CN","Chinanet","293","Chinanet AH","10800","socks4","5000","96","50","52","2026-07-12T01:45:53.647Z","434"
"206.123.156.215","elite","AS213790","GB","Limited Network LTD","14","Secure Internet LLC","9952","socks5","65","86","60","70","2026-07-12T02:07:37.224Z","463"
"85.117.248.36","elite","AS210086","ES","Connecta 1876 SLU","29","1 NEXIATEL","1080","socks5","2907","100","89","89","2026-07-12T01:41:44.010Z","476"
"125.227.45.186","elite","AS3462","TW","Chunghwa Telecom Co., Ltd.","253","Chunghwa Telecom Co. Ltd.","5001","socks5","5979","70","64","92","2026-07-12T01:19:43.024Z","477"
"193.43.140.240","transparent","AS29256","SY","Syrian Telecom","69","Wafa Telecom J.S.C","8080","http","265","95","59","62","2026-07-12T01:13:47.409Z","477"
"175.6.75.144","transparent","AS63835","CN","No.293, Wanbao Avenue","288","Chinanet HN","10064","https","701","76","19","25","2026-07-12T01:12:19.329Z","490"
"119.40.98.27","elite","AS10109","MN","Topica Co., Ltd","109","Topica Co., Ltd","8069","socks4","5002","100","38","38","2026-07-12T01:33:53.928Z","492"
"119.148.62.42","elite","AS23923","BD","Agni Systems Ltd. SUB","208","Agni Systems Limited","22122","socks5","5002","100","46","46","2026-07-12T01:35:34.118Z","496"
"173.249.20.169","elite","AS51167","FR","Contabo GmbH","8","Contabo GmbH","9060","socks5","269","100","9","9","2026-07-12T01:29:33.018Z","497"
"192.252.209.155","elite","AS46562","US","Performive LLC","148","Performive LLC","14455","socks5","5001","98","43","44","2026-07-12T01:43:48.330Z","506"
"146.158.107.138","elite","AS210616","RU","SM Ltd.","92","SM Ltd","9050","socks5","567","98","43","44","2026-07-12T01:28:18.928Z","516"
"103.127.94.10","transparent","AS135341","BD","Md Mahabub Alam","373","Relation Cable Network","8080","http","903","64","55","86","2026-07-12T01:27:32.718Z","522"
"185.181.209.34","elite","AS205399","TR","Hostigger INC.","38","Hostigger INC","8080","https","5586","99","72","73","2026-07-12T01:05:32.541Z","525"
"38.49.148.149","transparent","AS28458","MX","IENTC S de RL de CV","163","IENTC S de RL de CV","999","http","1066","99","80","81","2026-07-12T01:43:56.221Z","527"
"46.101.36.247","elite","AS14061","GB","DigitalOcean, LLC","23","Digitalocean","9050","socks4","39","100","84","84","2026-07-12T01:08:05.317Z","529"
"193.239.86.180","elite","AS9009","HK","M247 Europe SRL","200","M247 Ltd HONG KONG","80","http","2442","100","94","94","2026-07-12T01:30:54.529Z","531"
"181.209.59.178","transparent","AS52361","AR","ARSAT - Empresa Argentina de Soluciones Satelitales S.A","238","Lortnoc SRL","999","https","573","100","9","9","2026-07-12T01:44:23.107Z","552"
"206.123.156.217","elite","AS213790","GB","Limited Network LTD","16","Secure Internet LLC","6044","socks5","59","84","41","49","2026-07-12T02:18:38.430Z","573"
"86.57.178.182","elite","AS6697","BY","Republican Unitary Telecommunication Enterprise Beltelecom","37","PPPoE USERS GRODNO","4153","socks4","6710","100","12","12","2026-07-12T01:15:20.125Z","585"
"89.44.86.33","elite","AS205090","RU","First Server Limited","47","FIRST SERVER, SOCIEDAD LIMITADA","1080","socks5","19478","50","23","46","2026-07-12T01:44:11.488Z","588"
"36.64.27.123","elite","AS7713","ID","PT. Telekomunikasi Indonesia","180","N/A","5678","socks4","387","100","25","25","2026-07-12T01:03:21.218Z","593"
"168.245.197.146","elite","AS56882","ES","Aire Networks Del Mediterraneo SL Unipersonal","34","Aire Networks Del Mediterraneo SL Unipersonal","80","socks5","1092","61","56","92","2026-07-12T01:08:49.936Z","594"
"""

new_proxies = []
for i, line in enumerate(io.StringIO(csv_data)):
    if i == 0 or not line.strip(): continue # Skip header
    # Simple CSV parser since quotes are present
    row = next(csv.reader([line]))
    ip = row[0]
    port = row[7]
    protocol = row[8]
    
    # We can just extract IP:PORT format 
    new_proxies.append(f"{ip}:{port}")

# Filter out duplicates against existing working_proxies
existing_proxies = set()
if os.path.exists("c:/Users/yasha/Downloads/pillar1/working_proxies.txt"):
    with open("c:/Users/yasha/Downloads/pillar1/working_proxies.txt", "r") as f:
        for p in f:
            if p.strip(): existing_proxies.add(p.strip())

# Also load existing proxies.txt
if os.path.exists("c:/Users/yasha/Downloads/pillar1/proxies.txt"):
    with open("c:/Users/yasha/Downloads/pillar1/proxies.txt", "r") as f:
        for p in f:
            if p.strip(): existing_proxies.add(p.strip())

unique_new_proxies = [p for p in new_proxies if p not in existing_proxies]

with open("c:/Users/yasha/Downloads/pillar1/working_proxies.txt", "a") as f:
    for p in unique_new_proxies:
        f.write(p + "\\n")
        
with open("c:/Users/yasha/Downloads/pillar1/proxies.txt", "a") as f:
    for p in unique_new_proxies:
        f.write(p + "\\n")

print(f"Added {len(unique_new_proxies)} unique proxies.")
