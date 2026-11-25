import { FormEvent, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, euros } from '../api'
import AjouterListe from '../composants/AjouterListe'
import { EnTete, Erreur, useAction, useCharger } from '../composants/ui'
import { useSession } from '../contexte'
import type { Produit } from '../types'

// La carte du restaurant : entrées, plats, desserts et suppléments, avec leur prix TVA comprise.
// Une seule carte active. Un produit mis de côté (désactivé) n'est plus proposé sur les fiches, mais
// les fiches et devis qui l'ont déjà le gardent, et il se remet sur la carte d'un clic.
// Supprimer n'est possible que s'il n'a jamais servi.

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
  const [voirCote, setVoirCote] = useState(false)
  const { donnees, setDonnees, erreur, recharger } = useCharger(() => api.get<Produit[]>('/api/produits'))
  const action = useAction()

  const carte = (donnees ?? []).filter((p) => SECTIONS.some((s) => s.cle === p.categorie))
  const trouve = (p: Produit) => !q || p.nom.toLowerCase().includes(q.toLowerCase())
  const deCote = carte.filter((p) => !p.actif)
  const deCoteVisibles = deCote.filter(trouve)
  const nbActifs = carte.length - deCote.length

  // Arrivée depuis « Compléter le prix » d'un devis : montrer la ligne, même mise de côté.
  useEffect(() => {
    if (!cible || !donnees) return
    if (donnees.find((p) => p.id === cible && !p.actif)) setVoirCote(true)
    setTimeout(() => document.getElementById(`produit-${cible}`)?.scrollIntoView({ block: 'center' }), 50)
  }, [cible, donnees])

  const apresChangement = () => { rechargerCompteur(); rechargerReferences() }
  const enregistrer = async (p: Produit, changement: Record<string, unknown>) => {
    const r = await action.lancer(() => api.patch<Produit>(`/api/produits/${p.id}`, changement))
    if (r) { setDonnees((liste) => liste?.map((x) => (x.id === r.id ? r : x)) ?? null); apresChangement() }
  }
  const toutMettreDeCote = async () => {
    if (!window.confirm(`Mettre de côté les ${nbActifs} produits de la carte actuelle ? Rien n'est supprimé : `
      + 'ils restent dans « Mis de côté » et se remettent sur la carte d\'un clic.')) return
    if (await action.lancer(() => api.post('/api/produits/carte/mettre-de-cote', {}))) { recharger(); apresChangement() }
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
      <EnTete titre="Carte" sousTitre="Ce qu'on propose sur les fiches, avec les prix TVA comprise. Quand la carte change : coller la nouvelle carte dans « Changer de carte » en bas de page, l'ancienne est mise de côté toute seule.">
        {peutModifier && nbActifs > 0 && <button type="button" disabled={action.enCours} onClick={toutMettreDeCote}>Mettre toute la carte de côté</button>}
      </EnTete>
      {!peutModifier && <div className="bandeau info">Lecture seule : seuls les administrateurs (ou le droit « prix ») modifient la carte.</div>}
      <Erreur message={erreur || action.erreur} />
      <div className="filtres">
        <input placeholder="Chercher un produit…" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>

      {SECTIONS.map((s) => {
        const tous = carte.filter((p) => p.categorie === s.cle)
        const visibles = tous.filter((p) => p.actif && trouve(p))
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
                      className={`${p.prix_manquant ? 'ligne-alerte' : ''}${p.id === cible ? ' ligne-cible' : ''}`}>
                      <td>
                        {peutModifier
                          ? <input defaultValue={p.nom} key={p.nom} onBlur={(e) => e.target.value.trim() && e.target.value.trim() !== p.nom && enregistrer(p, { nom: e.target.value.trim() })} />
                          : p.nom}
                      </td>
                      <td className="droite" style={{ width: 170 }}>
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
                      <td className="droite" style={{ whiteSpace: 'nowrap', width: 1 }}>
                        {peutModifier && <button type="button" disabled={action.enCours} onClick={() => enregistrer(p, { actif: false })}>Mettre de côté</button>}
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

      {deCote.length > 0 && (
        <section className="carte">
          <h2>Mis de côté <span className="muet">({deCote.length})</span></h2>
          <p className="aide">
            Les anciennes cartes. Plus proposés sur les fiches ni comptés dans « Prix manquants » ; les fiches et devis
            qui les ont les gardent. Un plat qui revient se remet d'un clic, ou tout seul s'il est dans la nouvelle carte collée.
          </p>
          <button type="button" onClick={() => setVoirCote(!voirCote)}>{voirCote ? 'Masquer' : 'Voir'} les produits mis de côté</button>
          {voirCote && (deCoteVisibles.length > 0 ? (
            <table className="tableau">
              <thead><tr><th>Nom</th><th>Type</th><th className="droite">Dernier prix</th><th /></tr></thead>
              <tbody>
                {deCoteVisibles.map((p) => (
                  <tr key={p.id} id={`produit-${p.id}`} className={`muet${p.id === cible ? ' ligne-cible' : ''}`}>
                    <td>{p.nom}</td>
                    <td>{SECTIONS.find((s) => s.cle === p.categorie)?.titre}</td>
                    <td className="droite">{euros(p.prix_centimes)}</td>
                    <td className="droite" style={{ whiteSpace: 'nowrap', width: 1 }}>
                      {peutModifier && <button type="button" disabled={action.enCours} onClick={() => enregistrer(p, { actif: true })}>Remettre sur la carte</button>}
                      {' '}
                      {peutModifier && <button type="button" className="danger" disabled={action.enCours} onClick={() => supprimer(p)} title="Seulement s'il n'a jamais servi">Supprimer</button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <p className="muet">Aucun résultat.</p>)}
        </section>
      )}

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
