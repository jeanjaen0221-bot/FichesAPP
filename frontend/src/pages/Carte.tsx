import { FormEvent, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, euros } from '../api'
import AjouterListe from '../composants/AjouterListe'
import { EnTete, Erreur, useAction, useCharger } from '../composants/ui'
import { useSession } from '../contexte'
import type { Produit } from '../types'

// La carte du restaurant : entrées, plats, desserts et suppléments, avec leur prix TVA comprise.
// Une seule carte active. Un produit retiré (désactivé) n'est plus proposé sur les fiches, mais
// les fiches et devis qui l'ont déjà le gardent. Supprimer n'est possible que s'il n'a jamais servi.

const SECTIONS = [
  { cle: 'entree', titre: 'Entrées' }, { cle: 'plat', titre: 'Plats' },
  { cle: 'dessert', titre: 'Desserts' }, { cle: 'supplement', titre: 'Suppléments', aide: 'Planche apéro, coupes, extras…' },
]
const versSaisie = (c: number | null) => (c === null ? '' : (c / 100).toFixed(2).replace('.', ','))

export default function Carte() {
  const { moi, rechargerCompteur, rechargerReferences } = useSession()
  const peutModifier = moi.peut.prix
  const [params] = useSearchParams()
  const cible = params.get('produit')
  const [q, setQ] = useState('')
  const [voirRetires, setVoirRetires] = useState(false)
  const { donnees, setDonnees, erreur, recharger } = useCharger(() => api.get<Produit[]>('/api/produits'))
  const action = useAction()

  const carte = (donnees ?? []).filter((p) => SECTIONS.some((s) => s.cle === p.categorie))
  const retires = carte.filter((p) => !p.actif).length

  // Arrivée depuis « Compléter le prix » d'un devis : montrer la ligne, même retirée.
  useEffect(() => {
    if (!cible || !donnees) return
    if (donnees.find((p) => p.id === cible && !p.actif)) setVoirRetires(true)
    setTimeout(() => document.getElementById(`produit-${cible}`)?.scrollIntoView({ block: 'center' }), 50)
  }, [cible, donnees])

  const apresChangement = () => { rechargerCompteur(); rechargerReferences() }
  const enregistrer = async (p: Produit, changement: Record<string, unknown>) => {
    const r = await action.lancer(() => api.patch<Produit>(`/api/produits/${p.id}`, changement))
    if (r) { setDonnees((liste) => liste?.map((x) => (x.id === r.id ? r : x)) ?? null); apresChangement() }
  }
  const supprimer = async (p: Produit) => {
    if (!window.confirm(`Supprimer « ${p.nom} » ? (seulement s'il n'a jamais servi sur une fiche ou un devis)`)) return
    if (await action.lancer(() => api.delete(`/api/produits/${p.id}`))) {
      setDonnees((liste) => liste?.filter((x) => x.id !== p.id) ?? null)
      apresChangement()
    }
  }

  return (
    <>
      <EnTete titre="Carte" sousTitre="Ce qu'on propose sur les fiches, avec les prix TVA comprise. Quand la carte change : « Ajouter une liste ou changer de carte » en bas de page." />
      {!peutModifier && <div className="bandeau info">Lecture seule : seuls les administrateurs (ou le droit « prix ») modifient la carte.</div>}
      <Erreur message={erreur || action.erreur} />
      <div className="filtres">
        <input placeholder="Chercher un produit…" value={q} onChange={(e) => setQ(e.target.value)} />
        {retires > 0 && (
          <label className="case">
            <input type="checkbox" style={{ minWidth: 0 }} checked={voirRetires} onChange={(e) => setVoirRetires(e.target.checked)} />
            {' '}Voir les produits retirés de la carte ({retires})
          </label>
        )}
      </div>

      {SECTIONS.map((s) => {
        const tous = carte.filter((p) => p.categorie === s.cle)
        const visibles = tous.filter((p) => (voirRetires || p.actif) && (!q || p.nom.toLowerCase().includes(q.toLowerCase())))
        return (
          <section className="carte" key={s.cle}>
            <h2>
              {s.titre} <span className="muet">({tous.filter((p) => p.actif).length})</span>
              {tous.some((p) => p.actif && p.prix_manquant) && (
                <span className="texte-alerte"> · {tous.filter((p) => p.actif && p.prix_manquant).length} sans prix</span>
              )}
            </h2>
            {s.aide && <p className="aide">{s.aide}</p>}
            {visibles.length > 0 ? (
              <table className="tableau">
                <thead><tr><th>Nom</th><th className="droite">Prix TVA comprise</th><th /></tr></thead>
                <tbody>
                  {visibles.map((p) => (
                    <tr key={p.id} id={`produit-${p.id}`}
                      className={`${!p.actif ? 'barre-texte' : p.prix_manquant ? 'ligne-alerte' : ''}${p.id === cible ? ' ligne-cible' : ''}`}>
                      <td>
                        {peutModifier && p.actif
                          ? <input defaultValue={p.nom} key={p.nom} onBlur={(e) => e.target.value.trim() && e.target.value.trim() !== p.nom && enregistrer(p, { nom: e.target.value.trim() })} />
                          : p.nom}
                      </td>
                      <td className="droite" style={{ width: 170 }}>
                        {peutModifier && p.actif ? (
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
                      <td className="droite" style={{ whiteSpace: 'nowrap', width: 1 }}>
                        {peutModifier && (p.actif
                          ? <button type="button" disabled={action.enCours} onClick={() => enregistrer(p, { actif: false })}>Retirer de la carte</button>
                          : <button type="button" disabled={action.enCours} onClick={() => enregistrer(p, { actif: true })}>Remettre sur la carte</button>)}
                        {' '}
                        {peutModifier && <button type="button" className="danger" disabled={action.enCours} onClick={() => supprimer(p)} title="Seulement s'il n'a jamais servi">Supprimer</button>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : <p className="muet">{q ? 'Aucun résultat.' : 'Rien sur la carte.'}</p>}
            {peutModifier && <AjoutRapide categorie={s.cle} apresAjout={() => { recharger(); apresChangement() }} />}
          </section>
        )
      })}

      {peutModifier && <AjouterListe apresImport={() => { recharger(); apresChangement() }} />}
    </>
  )
}

function AjoutRapide({ categorie, apresAjout }: { categorie: string; apresAjout: () => void }) {
  const [nom, setNom] = useState('')
  const [prix, setPrix] = useState('')
  const action = useAction()
  const ajouter = async (e: FormEvent) => {
    e.preventDefault()
    if (!nom.trim()) return
    if (await action.lancer(() => api.post<Produit>('/api/produits', { nom: nom.trim(), categorie, unite: 'piece', prix }))) {
      setNom(''); setPrix(''); apresAjout()
    }
  }
  return (
    <form className="ligne-champs" onSubmit={ajouter}>
      <input placeholder="Ajouter…" value={nom} onChange={(e) => setNom(e.target.value)} style={{ flex: 1, minWidth: 220 }} />
      <input inputMode="decimal" placeholder="prix (facultatif)" value={prix} onChange={(e) => setPrix(e.target.value)} style={{ width: 140 }} />
      <button disabled={action.enCours || !nom.trim()}>Ajouter</button>
      <Erreur message={action.erreur} />
    </form>
  )
}
