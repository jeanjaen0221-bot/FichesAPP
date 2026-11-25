import { FormEvent, useEffect, useState } from 'react'
import { Link, Navigate, useSearchParams } from 'react-router-dom'
import { api, euros } from '../api'
import { Champ, EnTete, Erreur, useAction, useCharger } from '../composants/ui'
import { useSession } from '../contexte'
import type { Produit } from '../types'

const ONGLETS = [
  { cle: 'formule_repas', libelle: 'Formules repas' }, { cle: 'formule_boissons', libelle: 'Formules boissons' },
  { cle: 'coupe', libelle: 'Coupes' }, { cle: 'privatisation', libelle: 'Privatisations' },
]
// Entrées, plats, desserts et suppléments se gèrent dans le menu Carte.
const CARTE = ['entree', 'plat', 'dessert', 'supplement']
const NOMS_CATEGORIES: Record<string, string> = {
  formule_repas: 'Formule repas', formule_boissons: 'Formule boissons', coupe: 'Coupe', entree: 'Entrée',
  plat: 'Plat', dessert: 'Dessert', supplement: 'Supplément', privatisation: 'Privatisation',
}

/** Saisie en euros : « 4,31 » ; vide = prix manquant. */
const versSaisie = (c: number | null) => (c === null ? '' : (c / 100).toFixed(2).replace('.', ','))

export default function Prix() {
  const { moi, rechargerCompteur, rechargerReferences } = useSession()
  const peutModifier = moi.peut.prix
  const [params, setParams] = useSearchParams()
  const manquants = params.get('manquants') === '1'
  const cible = params.get('produit')
  const [onglet, setOnglet] = useState(ONGLETS[0].cle)
  const [q, setQ] = useState('')
  const { donnees: produits, setDonnees, erreur, recharger } = useCharger(() => api.get<Produit[]>('/api/produits'))
  const action = useAction()
  const [nouveau, setNouveau] = useState({ nom: '', categorie: 'privatisation', unite: 'forfait', prix: '' })

  // Arrivée depuis « Compléter le prix » d'un devis : ouvrir le bon onglet.
  useEffect(() => {
    if (!cible || !produits) return
    const p = produits.find((x) => x.id === cible)
    const o = p && ONGLETS.find((x) => x.cle.split(',').includes(p.categorie))
    if (o) setOnglet(o.cle)
    setTimeout(() => document.getElementById(`produit-${cible}`)?.scrollIntoView({ block: 'center' }), 50)
  }, [cible, produits])

  // « Compléter le prix » d'un devis sur un plat : c'est dans la Carte.
  const cibleCarte = cible && produits?.find((p) => p.id === cible && CARTE.includes(p.categorie))
  const nbManquants = produits?.filter((p) => p.prix_manquant && p.actif).length ?? 0
  const manquantsPar = (categories: string | string[]) =>
    produits?.filter((p) => p.prix_manquant && p.actif && ([] as string[]).concat(categories).includes(p.categorie)).length ?? 0
  const nbManquantsCarte = manquantsPar(CARTE)
  const visibles = (produits ?? []).filter((p) =>
    (manquants ? p.prix_manquant && p.actif : onglet.split(',').includes(p.categorie)) &&
    (!q || p.nom.toLowerCase().includes(q.toLowerCase())))

  const enregistrer = async (p: Produit, changement: Record<string, unknown>) => {
    const r = await action.lancer(() => api.patch<Produit>(`/api/produits/${p.id}`, changement))
    if (r) {
      setDonnees((liste) => liste?.map((x) => (x.id === r.id ? r : x)) ?? null)
      rechargerCompteur()
      rechargerReferences()
    }
  }

  const ajouter = async (e: FormEvent) => {
    e.preventDefault()
    const r = await action.lancer(() => api.post<Produit>('/api/produits', nouveau))
    if (r) {
      setNouveau({ ...nouveau, nom: '', prix: '' })
      recharger()
      rechargerCompteur()
      rechargerReferences()
    }
  }

  if (cibleCarte) return <Navigate to={`/carte?produit=${cibleCarte.id}`} replace />

  return (
    <>
      <EnTete titre="Prix" sousTitre="Tout ce qui se vend, TVA comprise. Changer un prix ne modifie pas les devis déjà préparés : seulement les nouveaux et ceux qu'on recalcule.">
        <button className={manquants ? 'principal' : ''} onClick={() => setParams(manquants ? {} : { manquants: '1' })}>
          Prix manquants ({nbManquants})
        </button>
      </EnTete>
      {!peutModifier && <div className="bandeau info">Lecture seule : seuls les administrateurs (ou le droit « prix ») modifient les prix.</div>}
      <Erreur message={erreur || action.erreur} />
      {manquants && <p className="aide">Tous les produits sans prix, d'où qu'ils viennent. Les entrées, plats, desserts et suppléments sont rangés dans le menu <Link to="/carte">Carte</Link>, pas dans les onglets ci-dessous : le lien de chaque ligne mène à sa liste. Le prix peut aussi être complété directement ici.</p>}
      {!manquants && (
        <p className="aide">
          Les entrées, plats, desserts et suppléments sont dans le menu <Link to="/carte">Carte</Link>
          {nbManquantsCarte > 0 && <span className="texte-alerte"> ({nbManquantsCarte} sans prix)</span>}.
        </p>
      )}
      {!manquants && (
        <div className="onglets">
          {ONGLETS.map((o) => <button key={o.cle} className={onglet === o.cle ? 'actif' : ''} onClick={() => setOnglet(o.cle)}>{o.libelle}{manquantsPar(o.cle) > 0 && <span className="texte-alerte"> ({manquantsPar(o.cle)} sans prix)</span>}</button>)}
        </div>
      )}
      <div className="filtres"><input placeholder="Filtrer par nom…" value={q} onChange={(e) => setQ(e.target.value)} /></div>
      <section className="carte">
        <table className="tableau">
          <thead><tr><th>Nom</th><th>Catégorie</th><th>Unité</th><th className="droite">Prix TVA comprise</th><th>Actif</th></tr></thead>
          <tbody>
            {visibles.map((p) => (
              <tr key={p.id} id={`produit-${p.id}`} className={`${p.prix_manquant ? 'ligne-alerte' : ''}${p.id === cible ? ' ligne-cible' : ''}`}>
                <td>
                  {peutModifier
                    ? <input defaultValue={p.nom} key={p.nom} onBlur={(e) => e.target.value.trim() !== p.nom && enregistrer(p, { nom: e.target.value })} />
                    : p.nom}
                </td>
                <td>
                  {!manquants ? NOMS_CATEGORIES[p.categorie]
                    : CARTE.includes(p.categorie)
                      ? <>{NOMS_CATEGORIES[p.categorie]} · <Link to={`/carte?produit=${p.id}`}>voir dans la Carte</Link></>
                      : <>{NOMS_CATEGORIES[p.categorie]} · <Link to={`/prix?produit=${p.id}`}>voir dans {ONGLETS.find((o) => o.cle === p.categorie)?.libelle ?? 'sa liste'}</Link></>}
                </td>
                <td>
                  {peutModifier ? (
                    <select value={p.unite} onChange={(e) => enregistrer(p, { unite: e.target.value })}>
                      <option value="par_personne">par personne</option><option value="piece">pièce</option>
                      <option value="forfait">forfait</option><option value="bouteille">bouteille</option>
                    </select>
                  ) : p.unite_libelle}
                </td>
                <td className="droite">
                  {peutModifier ? (
                    <span className="saisie-prix">
                      <input inputMode="decimal" placeholder="à compléter" defaultValue={versSaisie(p.prix_centimes)} key={String(p.prix_centimes)}
                        onBlur={(e) => {
                          const valeur = e.target.value.trim()
                          if (valeur === versSaisie(p.prix_centimes)) return
                          if (valeur && Number(valeur.replace(',', '.')) === 0 && !window.confirm(`${p.nom} : gratuit ?`)) {
                            e.target.value = versSaisie(p.prix_centimes)
                            return
                          }
                          enregistrer(p, { prix: valeur })
                        }} /> €
                    </span>
                  ) : euros(p.prix_centimes)}
                </td>
                <td>
                  <input type="checkbox" checked={p.actif} disabled={!peutModifier} onChange={(e) => enregistrer(p, { actif: e.target.checked })} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {visibles.length === 0 && <p className="muet">{manquants ? 'Tous les prix sont complétés.' : 'Rien dans cette catégorie.'}</p>}
      </section>

      {peutModifier && (
        <form className="carte" onSubmit={ajouter}>
          <h2>Ajouter</h2>
          <div className="ligne-champs">
            <Champ libelle="Nom"><input value={nouveau.nom} onChange={(e) => setNouveau({ ...nouveau, nom: e.target.value })} required /></Champ>
            <Champ libelle="Catégorie">
              <select value={nouveau.categorie} onChange={(e) => setNouveau({ ...nouveau, categorie: e.target.value })}>
                {Object.entries(NOMS_CATEGORIES).filter(([cle]) => !CARTE.includes(cle)).map(([cle, nom]) => <option key={cle} value={cle}>{nom}</option>)}
              </select>
            </Champ>
            <Champ libelle="Unité">
              <select value={nouveau.unite} onChange={(e) => setNouveau({ ...nouveau, unite: e.target.value })}>
                <option value="par_personne">par personne</option><option value="piece">pièce</option>
                <option value="forfait">forfait</option><option value="bouteille">bouteille</option>
              </select>
            </Champ>
            <Champ libelle="Prix TVA comprise" aide="Vide = à compléter plus tard."><input inputMode="decimal" placeholder="ex. 24,50" value={nouveau.prix} onChange={(e) => setNouveau({ ...nouveau, prix: e.target.value })} /></Champ>
            <button className="principal" disabled={action.enCours}>Ajouter</button>
          </div>
          <p className="aide">Une nouvelle formule repas ou boissons se crée dans le menu Formules. Les plats et suppléments s'ajoutent dans la <Link to="/carte">Carte</Link>.</p>
        </form>
      )}
    </>
  )
}
