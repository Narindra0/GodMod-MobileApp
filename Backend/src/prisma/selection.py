def determiner_seuil_dynamique(taux_succes):
    if taux_succes < 0.35:
        return 10.0, "DÉFENSIF (Crise)"
    if taux_succes < 0.55:
        return 8.5, "PRUDENT"
    if taux_succes > 0.80:
        return 6.0, "OFFENSIF"
    return 7.0, "Standard"


def filtrer_meilleurs_matchs(predictions, max_preds=2):
    valid_preds = [p for p in predictions if p.get("prediction")]
    valid_preds.sort(key=lambda x: x["confiance"], reverse=True)
    return valid_preds[:max_preds]
