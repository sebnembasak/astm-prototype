from typing import List, Tuple, Dict
import numpy as np
from scipy.spatial import cKDTree
from datetime import datetime, timedelta, timezone

Vec3 = Tuple[float, float, float]  # # 3 Boyutlu Vektör Tipi (x, y, z)


def build_kdtree(states: Dict[int, Vec3]) -> cKDTree:
    """
    Verilen konum listesinden bir KD-Tree veri yapısı oluşturur.
    KD-Tree, uzayı hiperdüzlemlerle bölerek hızlı arama yapmayı sağlar.
    """
    positions = np.array(list(states.values()))
    tree = cKDTree(positions)
    return tree


def prune_pairs(states: Dict[int, Vec3], radius_km: float = 100.0) -> List[Tuple[int, int]]:
    """
    Pruning yani Budama işlemi
    Bu fonksiyon tüm uyduları birbiriyle karşılaştırmak (brute force) yerine,
    sadece birbirine 'radius_km' kadar yakın olan çiftleri bulur.
    O(N logN) olarak çalışır. Sadece yakın çiftleri return eder.
    Args:
        states: {sat_id: (x, y, z)} formatında uyduların anlık konumları.
        radius_km: Arama yarıçapı (örn. 100km))

    Returns:
        List[Tuple[int, int]]: Çarpışma riski taşıyan aday çiftlerin id listesi.
        Örn: [(25544, 49044), (12345, 67890)]
    """

    if len(states) < 2:  # Eğer 2'den az uydu varsa karşılaştırma yapılamaz, boş liste dön.
        return []

    # Dictionary yapısını dcipy nin anlayacağı numpy dizilerine çevir
    # sat_ids listesi ile positions dizisinin indeksleri birebir maplenmeli
    sat_ids = list(states.keys())
    positions = np.array([states[s] for s in sat_ids])

    # veri boyutunu kontrol et, n uydu 3 boyutlu uzay
    if positions.ndim != 2 or positions.shape[0] < 2:
        return []

    # İndeksleme (KD-Tree İnşası)
    # Uzaydaki noktaları hızlı sorgulanabilir bir ağaç yapısına diziyoruz
    # bir epoch için tüm uyduların pozisyon haritası (sat_id → (x,y,z))'tir.
    # Burada pozisyonlar için TEME veya ECEF kullanılabilir. Ama her epoch'da aynı frame kullanıldığına emin olunmalı

    tree = cKDTree(positions)
    pairs = set()  # yarıçap içindeki sorgu çiftleri, tekrar olmasın diye set ile

    # # Her bir uydu için "Bana x km yakınımdaki komşuları getir" sorusunu soruyoruz
    for i, pos in enumerate(positions):
        idxs = tree.query_ball_point(pos, r=radius_km)
        for j in idxs:
            if j <= i:
                # j == i ise zaten uydunun kendisidir, kontrole gerek yok
                # j < i ise biz A,B çiftini bulduysak B,A çiftine bir daha bakmaya gerek yok
                # Bu sayede işlem sayısı yarıya inecektir ve gereksiz kopayalar olmayacaktır
                continue
            # # İndeksleri gerçek uydu idlerine (NORAD ID) çevirip listeye ekle
            pairs.add((sat_ids[i], sat_ids[j]))
    # Set yapısını listeye çevirip döndür. Artık elimizde sadece
    # gerçekten birbirine yakın olan, SGP4 ile incelenmeye değer adaylar var.
    return list(pairs)

