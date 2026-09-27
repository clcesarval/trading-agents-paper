"""Shared, dependency-free test data for the headline classifier experiments."""

LABELS = {
    "positivo": "boa notícia para o preço da ação",
    "negativo": "má notícia para o preço da ação",
    "neutro": "informativa, sem efeito claro no preço",
}

# Obvious-by-construction Portuguese headlines (label chosen before running anything).
LABELLED = [
    ("Petrobras anuncia lucro recorde e aumenta dividendos", "positivo"),
    ("PETR4 dispara após descoberta de petróleo na Margem Equatorial", "positivo"),
    ("Petrobras eleva produção e supera expectativas do mercado", "positivo"),
    ("Ibovespa fecha em alta com valorização das commodities", "positivo"),
    ("Analistas elevam preço-alvo da Petrobras e recomendam compra", "positivo"),
    ("Petrobras tem prejuízo bilionário e corta dividendos", "negativo"),
    ("PETR4 despenca com queda do petróleo e temor de intervenção do governo", "negativo"),
    ("Petrobras é multada e vê produção cair mais do que o esperado", "negativo"),
    ("Ibovespa tem forte queda e ações da Petrobras lideram perdas", "negativo"),
    ("Bancos rebaixam recomendação da Petrobras para venda", "negativo"),
    ("Petrobras divulga calendário de divulgação de resultados do trimestre", "neutro"),
    ("Petrobras realiza assembleia de acionistas na próxima semana", "neutro"),
    ("Empresa informa mudança de endereço de sua sede administrativa", "neutro"),
    ("Petrobras publica relatório anual de sustentabilidade", "neutro"),
]
