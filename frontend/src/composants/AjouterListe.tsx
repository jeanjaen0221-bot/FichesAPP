import { useRef, useState } from 'react'
import { api, Echec } from '../api'
import { Champ, Erreur, useAction } from './ui'

// Menu Carte → « Ajouter une liste / nouvelle carte » : coller une carte (ou lire un PDF / texte / CSV), voir ce
// que fera l'import ligne par ligne, puis importer. Le serveur relit le texte à l'import : ce
// qui est importé est exactement ce que montre l'aperçu, rien n'est écrit avant.

type Action = 'creer' | 'completer_prix' | 'remplacer_prix' | 'reactiver' | 'inchange' | 'prix_different' | 'erreur' | 'desactiver'
type LigneListe = {
  numero: number | null; texte: string; produit_id: string | null; nom: string | null; categorie: string | null; prix: string | null
  prix_actuel: string | null; action: Action; action_libelle: string; message: string | null
}
type Resultat = { lignes: LigneListe[]; resume: Record<Action, number> }

const TYPES: Record<string, string> = { entree: 'Entrée', plat: 'Plat', dessert: 'Dessert', supplement: 'Supplément' }
const COULEURS: Record<Action, string> = {
  creer: 'vert', completer_prix: 'bleu', remplacer_prix: 'ambre', reactiver: 'cyan',
  inchange: 'gris', prix_different: 'ambre', erreur: 'rouge', desactiver: 'violet',
}
const A_ECRIRE: Action[] = ['creer', 'completer_prix', 'remplacer_prix', 'reactiver', 'desactiver']
const EXEMPLE = `Entrées
Carpaccio de bœuf ........ 14,50 €
Croquettes aux crevettes 16

Plats
Steak frites, sauce au poivre 26 €

Dame blanche | dessert | 8,00
Planche apéro | supplément`

export default function AjouterListe({ apresImport }: { apresImport: () => void }) {
  const [texte, setTexte] = useState('')
  const [typeDefaut, setTypeDefaut] = useState('')
  const [remplacer, setRemplacer] = useState(false)
  // Quand la carte change, elle change entièrement : par défaut, la liste collée remplace la carte.
  const [nouvelleCarte, setNouvelleCarte] = useState(true)
  const [apercu, setApercu] = useState<Resultat | null>(null)
  const [fait, setFait] = useState<Resultat | null>(null)
  const [voirTout, setVoirTout] = useState(false)
  const fichier = useRef<HTMLInputElement>(null)
  const action = useAction()

  // Toute modification rend l'aperçu périmé : il faut le refaire avant d'importer.
  const changer = (maj: () => void) => { maj(); setApercu(null); setFait(null) }
  const corps = () => ({ texte, categorie_defaut: typeDefaut || null, remplacer_prix: remplacer, nouvelle_carte: nouvelleCarte })

  const voirApercu = async () => {
    const r = await action.lancer(() => api.post<Resultat>('/api/produits/liste/apercu', corps()))
    if (r) { setApercu(r); setVoirTout(false) }
  }

  const importer = async () => {
    const r = await action.lancer(() => api.post<Resultat>('/api/produits/liste', corps()))
    if (r) { setFait(r); setApercu(null); setTexte(''); apresImport() }
  }

  const lireFichier = async (f?: File) => {
    if (!f) return
    if (texte.trim() && !window.confirm('Remplacer le texte déjà collé par celui du fichier ?')) return
    const formulaire = new FormData()
    formulaire.append('fichier', f)
    const r = await action.lancer(async () => {
      const reponse = await fetch('/api/produits/liste/fichier', { method: 'POST', body: formulaire, credentials: 'same-origin', headers: { 'X-Albert': '1' } })
      const donnees = await reponse.json().catch(() => null)
      if (!reponse.ok) throw new Echec(reponse.status, donnees?.erreur ?? { code: 'erreur_serveur', message: 'Erreur inattendue.' })
      return donnees as { texte: string }
    })
    if (r) changer(() => setTexte(r.texte))
  }

  const aEcrire = apercu ? A_ECRIRE.reduce((n, a) => n + apercu.resume[a], 0) : 0
  // Par défaut, l'aperçu montre ce qui change et ce qui pose question ; « tout voir » ajoute le reste.
  const lignesVisibles = apercu ? apercu.lignes.filter((l) => voirTout || l.action !== 'inchange') : []

  return (
    <section className="carte">
      <h2>Changer de carte ou ajouter une liste</h2>
      <div className="onglets">
        <button type="button" className={nouvelleCarte ? 'actif' : ''} onClick={() => changer(() => setNouvelleCarte(true))}>Nouvelle carte (remplace l'actuelle)</button>
        <button type="button" className={!nouvelleCarte ? 'actif' : ''} onClick={() => changer(() => setNouvelleCarte(false))}>Ajouter à la carte actuelle</button>
      </div>
      {nouvelleCarte ? (
        <p className="aide">
          <strong>Toutes les entrées, plats et desserts actuels absents de la liste sont mis de côté.</strong> Les suppléments
          restent tous (ceux de la liste sont ajoutés ou mis à jour).
          Rien n'est supprimé : ils restent dans « Mis de côté », les fiches et devis qui les ont les gardent, et un plat
          repris dans la nouvelle carte revient avec son prix.
        </p>
      ) : <p className="aide">Les produits collés s'ajoutent ; rien n'est mis de côté.</p>}
      <p className="aide">
        Coller la carte telle quelle ou une ligne par produit. Les intertitres (« Entrées », « Plats », « Desserts », « Suppléments »)
        donnent le type des lignes qui suivent ; le prix TVA comprise peut être en fin de ligne (« … 14,50 € ») ou après
        un « | » : <code>Dame blanche | dessert | 8,00</code>. Sans prix, le produit est ajouté « à compléter ».
        Un produit déjà sur la carte n'est jamais créé deux fois.
        D'un PDF, seules les parties Entrées, Plats, Desserts et Suppléments sont reprises (le titre, les formules,
        les conditions sont laissés) : relire le texte avant l'aperçu et effacer ce qui n'est pas un plat.
      </p>
      <div className="ligne-champs">
        <Champ libelle="Type des lignes sans type" aide="Avant le premier intertitre.">
          <select value={typeDefaut} onChange={(e) => changer(() => setTypeDefaut(e.target.value))}>
            <option value="">— aucun (refuser la ligne) —</option>
            {Object.entries(TYPES).map(([cle, nom]) => <option key={cle} value={cle}>{nom}</option>)}
          </select>
        </Champ>
        <button type="button" onClick={() => fichier.current?.click()} disabled={action.enCours}>Lire un fichier (PDF, texte, CSV)…</button>
        <input ref={fichier} type="file" accept=".pdf,.txt,.csv,application/pdf,text/plain,text/csv" hidden
          onChange={(e) => { lireFichier(e.target.files?.[0]); e.target.value = '' }} />
      </div>
      <textarea rows={12} value={texte} placeholder={EXEMPLE} spellCheck={false}
        onChange={(e) => { const v = e.target.value; changer(() => setTexte(v)) }} />
      <div className="ligne-champs">
        <label className="case">
          <input type="checkbox" checked={remplacer} onChange={(e) => { const v = e.target.checked; changer(() => setRemplacer(v)) }} />
          {' '}Remplacer les prix déjà saisis quand la liste en donne un autre
        </label>
        <button type="button" className="principal" disabled={action.enCours || !texte.trim()} onClick={voirApercu}>Voir l'aperçu</button>
      </div>
      <Erreur message={action.erreur} />

      {fait && (
        <div className="bandeau info">
          Importé : {fait.resume.creer} nouveau(x) produit(s), {fait.resume.completer_prix + fait.resume.remplacer_prix} prix
          mis à jour, {fait.resume.reactiver} réactivé(s){fait.resume.desactiver > 0 && `, ${fait.resume.desactiver} ancien(s) mis de côté`}.
          {fait.resume.erreur > 0 && ` ${fait.resume.erreur} ligne(s) ignorée(s).`}
          {fait.lignes.some((l) => l.action === 'creer' && !l.prix) && ' Les produits sans prix sont dans « Prix manquants ».'}
        </div>
      )}

      {apercu && (
        <>
          <div className="bandeau attention">
            <strong>Aperçu — rien n'est encore enregistré.</strong>
            {(Object.keys(COULEURS) as Action[]).filter((a) => apercu.resume[a] > 0).map((a) => (
              <span key={a} className={`pastille ${COULEURS[a]}`}>{apercu.resume[a]} × {apercu.lignes.find((l) => l.action === a)?.action_libelle}</span>
            ))}
          </div>
          {apercu.resume.erreur > 0 && (nouvelleCarte
            ? <div className="bandeau erreur">Pour remplacer la carte, corriger ou effacer les lignes « Ignoré » puis refaire l'aperçu : une ligne illisible pourrait être un plat à garder.</div>
            : <p className="aide">Les lignes « Ignoré » ne seront pas importées : corriger le texte puis refaire l'aperçu, ou importer sans elles.</p>)}
          <table className="tableau">
            <thead><tr><th className="etroit">Ligne</th><th>Nom</th><th>Type</th><th className="droite">Prix</th><th>Ce qui sera fait</th><th>Remarque</th></tr></thead>
            <tbody>
              {lignesVisibles.map((l) => (
                <tr key={l.numero ?? `retire-${l.produit_id}`} className={l.action === 'erreur' || l.action === 'prix_different' ? 'ligne-alerte' : ''}>
                  <td className="muet">{l.numero ?? '—'}</td>
                  <td>{l.nom ?? <span className="muet">{l.texte}</span>}</td>
                  <td>{l.categorie ? TYPES[l.categorie] : '—'}</td>
                  <td className="droite">
                    {l.action === 'erreur' ? '—' : l.action === 'desactiver' ? l.prix_actuel : l.prix ?? <span className="muet">à compléter</span>}
                    {l.prix_actuel && l.prix && l.prix_actuel !== l.prix && <div className="aide">actuel : {l.prix_actuel}</div>}
                  </td>
                  <td><span className={`pastille ${COULEURS[l.action]}`}>{l.action_libelle}</span></td>
                  <td className="aide">{l.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {apercu.resume.inchange > 0 && (
            <button type="button" onClick={() => setVoirTout(!voirTout)}>
              {voirTout ? 'Masquer' : 'Voir aussi'} les {apercu.resume.inchange} produit(s) déjà sur la carte
            </button>
          )}
          <div className="ligne-champs">
            <button type="button" className="principal" disabled={action.enCours || aEcrire === 0 || (nouvelleCarte && apercu.resume.erreur > 0)} onClick={importer}>
              {aEcrire === 0 ? 'Rien à importer' : `Importer ${aEcrire} produit(s)`}
            </button>
          </div>
        </>
      )}
    </section>
  )
}
