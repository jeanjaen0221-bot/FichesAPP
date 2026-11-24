import { FormEvent, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, Echec, formatJour } from '../api'
import { Champ, EnTete, Erreur, useAction } from '../composants/ui'

type Params = Record<string, string | number | string[]>

const CHAMPS: { cle: string; libelle: string; aide?: string; long?: boolean }[] = [
  { cle: 'restaurant_nom', libelle: 'Nom du restaurant' },
  { cle: 'restaurant_adresse', libelle: 'Adresse', aide: 'Imprimée en haut des devis et des bons.' },
  { cle: 'restaurant_telephone', libelle: 'Téléphone' },
  { cle: 'restaurant_email', libelle: 'E-mail' },
  { cle: 'restaurant_tva', libelle: 'N° TVA du restaurant' },
  { cle: 'conditions_paiement_defaut', libelle: 'Conditions de paiement par défaut' },
  { cle: 'mentions_devis', libelle: 'Mentions en bas des devis', long: true },
]

export default function Parametres() {
  const [p, setP] = useState<Params | null>(null)
  const [ok, setOk] = useState(false)
  const { enCours, erreur, setErreur, lancer } = useAction()

  useEffect(() => { api.get<Params>('/api/parametres').then(setP).catch((e) => setErreur(e.message)) }, [setErreur])
  if (!p) return <Erreur message={erreur} />

  const enregistrer = async (e: FormEvent) => {
    e.preventDefault()
    const heures = String(p.heures_proposees).split(',').map((h) => h.trim()).filter(Boolean)
    const r = await lancer(() => api.patch<Params>('/api/parametres', { ...p, heures_proposees: heures }))
    if (r) { setP(r); setOk(true); setTimeout(() => setOk(false), 2000) }
  }

  return (
    <form onSubmit={enregistrer}>
      <EnTete titre="Paramètres"><button className="principal" disabled={enCours}>{ok ? 'Enregistré ✓' : 'Enregistrer'}</button></EnTete>
      <Erreur message={erreur} />
      <section className="carte">
        <div className="ligne-champs">
          {CHAMPS.map(({ cle, libelle, aide, long }) => (
            <Champ key={cle} libelle={libelle} aide={aide} large={long}>
              {long
                ? <textarea rows={3} value={String(p[cle] ?? '')} onChange={(e) => setP({ ...p, [cle]: e.target.value })} />
                : <input value={String(p[cle] ?? '')} onChange={(e) => setP({ ...p, [cle]: e.target.value })} />}
            </Champ>
          ))}
          <Champ libelle="Validité d'un devis (jours)">
            <input type="number" min={1} max={365} value={Number(p.validite_devis_jours)} onChange={(e) => setP({ ...p, validite_devis_jours: Number(e.target.value) })} />
          </Champ>
          <Champ libelle="Zenchef : importer les groupes de plus de (couverts)">
            <input type="number" min={0} max={500} value={Number(p.zenchef_seuil_couverts ?? 10)} onChange={(e) => setP({ ...p, zenchef_seuil_couverts: Number(e.target.value) })} />
          </Champ>
          <Champ libelle="Heures proposées sur la fiche" aide="Séparées par des virgules.">
            <input value={Array.isArray(p.heures_proposees) ? p.heures_proposees.join(', ') : String(p.heures_proposees)}
              onChange={(e) => setP({ ...p, heures_proposees: e.target.value })} />
          </Champ>
        </div>
      </section>
      <Allergenes />
      <Zenchef />
      <Gmail />
    </form>
  )
}

type AllergeneAjoute = { cle: string; libelle: string; icone: boolean }

// Allergènes en plus des 14 réglementaires : proposés sur la fiche, lus par ChatGPT, imprimés avec leur icône.
// Cette carte est dans le formulaire des paramètres : ses boutons sont de type « button » et Entrée est retenu.
function Allergenes() {
  const [liste, setListe] = useState<AllergeneAjoute[] | null>(null)
  const [libelle, setLibelle] = useState('')
  const [icone, setIcone] = useState<File | null>(null)
  const [version, setVersion] = useState(0)
  const champIcone = useRef<HTMLInputElement>(null)
  const { enCours, erreur, lancer } = useAction()
  const charger = () => api.get<AllergeneAjoute[]>('/api/allergenes').then(setListe).catch(() => {})
  useEffect(() => { charger() }, [])

  const envoyer = (chemin: string, champs: Record<string, string>, fichier?: File | null) => lancer(async () => {
    const formulaire = new FormData()
    for (const [cle, valeur] of Object.entries(champs)) formulaire.append(cle, valeur)
    if (fichier) formulaire.append('icone', fichier)
    const r = await fetch(chemin, { method: 'POST', body: formulaire, credentials: 'same-origin', headers: { 'X-Albert': '1' } })
    const corps = await r.json().catch(() => null)
    if (!r.ok) throw new Echec(r.status, corps?.erreur ?? { code: 'erreur_serveur', message: 'Erreur inattendue.' })
    return corps as AllergeneAjoute
  })

  const ajouter = async () => {
    if (!libelle.trim()) return
    if (await envoyer('/api/allergenes', { libelle: libelle.trim() }, icone)) {
      setLibelle(''); setIcone(null); if (champIcone.current) champIcone.current.value = ''; charger()
    }
  }
  const changerIcone = async (a: AllergeneAjoute, fichier?: File) => {
    if (fichier && await envoyer(`/api/allergenes/${a.cle}`, {}, fichier)) { setVersion((v) => v + 1); charger() }
  }
  const renommer = async (a: AllergeneAjoute) => {
    const nouveau = window.prompt('Nouveau libellé', a.libelle)
    if (nouveau && nouveau.trim() && nouveau.trim() !== a.libelle && await envoyer(`/api/allergenes/${a.cle}`, { libelle: nouveau.trim() })) charger()
  }
  const supprimer = async (a: AllergeneAjoute) => {
    if (window.confirm(`Supprimer l'allergène « ${a.libelle} » ?`) && await lancer(() => api.delete(`/api/allergenes/${a.cle}`))) charger()
  }

  return (
    <section className="carte">
      <h2>Allergènes ajoutés</h2>
      <p className="aide">En plus des 14 allergènes réglementaires : ils sont proposés sur la fiche, lus par ChatGPT et imprimés avec leur icône (PNG ou JPEG, 2 Mo au plus). Un allergène utilisé sur une fiche ne se supprime pas.</p>
      {liste && liste.length > 0 && (
        <table className="tableau">
          <tbody>
            {liste.map((a) => (
              <tr key={a.cle}>
                <td style={{ width: 40 }}>{a.icone && <img src={`/api/allergenes/${a.cle}/icone?v=${version}`} alt="" width={24} height={24} />}</td>
                <td><strong>{a.libelle}</strong> <span className="aide">({a.cle})</span></td>
                <td style={{ textAlign: 'right' }}>
                  <label className="bouton">
                    {a.icone ? "Changer l'icône" : 'Ajouter une icône'}
                    <input type="file" accept="image/png,image/jpeg" hidden onChange={(e) => { changerIcone(a, e.target.files?.[0]); e.target.value = '' }} />
                  </label>{' '}
                  <button type="button" disabled={enCours} onClick={() => renommer(a)}>Renommer</button>{' '}
                  <button type="button" className="danger" disabled={enCours} onClick={() => supprimer(a)}>Supprimer</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="ligne-champs">
        <Champ libelle="Nouvel allergène">
          <input value={libelle} placeholder="ex. Kiwi" onChange={(e) => setLibelle(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); ajouter() } }} />
        </Champ>
        <Champ libelle="Icône (facultatif)">
          <input type="file" accept="image/png,image/jpeg" ref={champIcone} onChange={(e) => setIcone(e.target.files?.[0] ?? null)} />
        </Champ>
        <button type="button" disabled={enCours || !libelle.trim()} onClick={ajouter}>Ajouter</button>
      </div>
      <Erreur message={erreur} />
    </section>
  )
}

type Synchro = { creees: { fiche_id: string; client: string; date: string; heure: string; couverts: number }[]; deja_importees: number; du: string; au: string }

function Zenchef() {
  const [configure, setConfigure] = useState<boolean | null>(null)
  const [resultat, setResultat] = useState<Synchro | null>(null)
  const { enCours, erreur, lancer } = useAction()
  useEffect(() => { api.get<{ configure: boolean }>('/api/zenchef').then((r) => setConfigure(r.configure)).catch(() => {}) }, [])
  return (
    <section className="carte">
      <h2>Zenchef</h2>
      {configure === false && <p className="aide">Non configuré : renseigner ZENCHEF_API_TOKEN et ZENCHEF_RESTAURANT_ID dans les variables du serveur.</p>}
      {configure && <>
        <p className="aide">Importe les réservations de groupe des 60 prochains jours en fiches brouillon (client retrouvé ou créé). Une réservation déjà importée n'est jamais recréée.</p>
        <button type="button" disabled={enCours} onClick={async () => setResultat((await lancer(() => api.post<Synchro>('/api/zenchef/synchroniser'))) ?? null)}>Synchroniser maintenant</button>
      </>}
      <Erreur message={erreur} />
      {resultat && (
        <div className="bandeau info">
          {resultat.creees.length} fiche(s) créée(s), {resultat.deja_importees} déjà importée(s).
          <ul>{resultat.creees.map((c) => <li key={c.fiche_id}><Link to={`/fiches/${c.fiche_id}`}>{c.client}</Link> — {formatJour(c.date)} {c.heure}, {c.couverts} couverts</li>)}</ul>
        </div>
      )}
    </section>
  )
}

type EtatGmail = { configure: boolean; relie: boolean; email: string | null; relie_le: string | null }

function Gmail() {
  const [etat, setEtat] = useState<EtatGmail | null>(null)
  const { enCours, erreur, lancer } = useAction()
  const retour = new URLSearchParams(window.location.search).get('gmail')
  const charger = () => api.get<EtatGmail>('/api/gmail').then(setEtat).catch(() => {})
  useEffect(() => { charger() }, [])
  if (!etat) return null
  return (
    <section className="carte">
      <h2>Gmail (lecture par ChatGPT)</h2>
      <p className="aide">Permet à ChatGPT de lire les demandes des clients pour remplir les fiches. Aucun envoi n'est possible.</p>
      {retour === 'ok' && <div className="bandeau info">Boîte reliée.</div>}
      {retour === 'refuse' && <div className="bandeau attention">Liaison annulée.</div>}
      {!etat.configure && <p className="aide">Non configuré : renseigner GMAIL_CLIENT_ID et GMAIL_CLIENT_SECRET (et GMAIL_ADRESSE) dans les variables du serveur.</p>}
      {etat.configure && (etat.relie
        ? <div className="ligne-champs"><span>Boîte reliée : <strong>{etat.email}</strong></span>
            <button type="button" className="danger" disabled={enCours} onClick={async () => { if (window.confirm('Délier la boîte Gmail ?') && await lancer(() => api.post('/api/gmail/delier'))) charger() }}>Délier</button></div>
        : <a className="bouton principal" href="/api/gmail/relier">Relier la boîte Gmail</a>)}
      <Erreur message={erreur} />
    </section>
  )
}
