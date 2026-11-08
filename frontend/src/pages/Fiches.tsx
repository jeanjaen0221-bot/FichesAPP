import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api, aujourdhui, ouvrirPdf } from '../api'
import { Chargement, EnTete, Erreur, Pastille, Statut, useCharger } from '../composants/ui'
import { useSession } from '../contexte'
import type { Fiche, LigneFiche } from '../types'

const PERIODES = [
  { cle: 'a_venir', libelle: 'À venir' },
  { cle: 'passees', libelle: 'Passées' },
  { cle: 'toutes', libelle: 'Toutes' },
]
const TYPES_PLATS = [
  { cle: 'entree', libelle: 'Entrées' },
  { cle: 'plat', libelle: 'Plats' },
  { cle: 'dessert', libelle: 'Desserts' },
]
const JOURS = ['Dimanche', 'Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi']
const MOIS = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre']

function dateLongue(iso: string) {
  const d = new Date(`${iso}T12:00:00`)
  return `${JOURS[d.getDay()]} ${d.getDate()} ${MOIS[d.getMonth()]} ${d.getFullYear()}`
}

function ecartJours(iso: string) {
  const jour = new Date(`${iso}T12:00:00`).getTime()
  const ref = new Date(`${aujourdhui()}T12:00:00`).getTime()
  return Math.round((jour - ref) / 86_400_000)
}

function reperage(iso: string) {
  const n = ecartJours(iso)
  if (n === 0) return { texte: "Aujourd'hui", classe: 'aujourdhui' }
  if (n === 1) return { texte: 'Demain', classe: 'proche' }
  if (n > 1 && n <= 7) return { texte: `Dans ${n} jours`, classe: 'proche' }
  if (n > 7 && n <= 31) return { texte: `Dans ${n} jours`, classe: '' }
  if (n === -1) return { texte: 'Hier', classe: 'passe' }
  if (n < -1 && n >= -31) return { texte: `Il y a ${-n} jours`, classe: 'passe' }
  return null
}

const actif = (f: Fiche) => f.statut !== 'annulee'
const plats = (f: Fiche) => f.lignes.filter((l) => l.type !== 'supplement')

/** Plats d'un type : total face aux couverts (complet, incomplet, en trop). */
function ResumeType({ libelle, lignes, couverts }: { libelle: string; lignes: LigneFiche[]; couverts: number }) {
  const total = lignes.reduce((n, l) => n + l.quantite, 0)
  const etat = total === couverts ? 'complet' : total > couverts ? 'trop' : 'incomplet'
  const detail = lignes.map((l) => `${l.quantite} × ${l.libelle}`).join('\n')
  return (
    <span className={`resume-type ${etat}`} title={detail}>
      {libelle} <b>{total}/{couverts}</b>
      {lignes.length > 1 && <small> · {lignes.length} lignes</small>}
    </span>
  )
}

function Repas({ f }: { f: Fiche }) {
  const lignes = plats(f)
  if (lignes.length === 0) {
    return f.formule_repas
      ? <span className="repas-formule">{f.formule_repas}</span>
      : <span className="repas-vide">Repas à définir</span>
  }
  return (
    <>
      {f.formule_repas && <span className="repas-formule">{f.formule_repas}</span>}
      {TYPES_PLATS.map(({ cle, libelle }) => {
        const duType = lignes.filter((l) => l.type === cle)
        return duType.length > 0 && <ResumeType key={cle} libelle={libelle} lignes={duType} couverts={f.couverts} />
      })}
    </>
  )
}

function Allergenes({ cles }: { cles: string[] }) {
  const { references } = useSession()
  if (cles.length === 0) return null
  const libelle = (cle: string) => references?.allergenes.find((a) => a.cle === cle)?.libelle ?? cle
  const visibles = cles.slice(0, 3)
  return (
    <span className="allergenes" title={cles.map(libelle).join(', ')}>
      {visibles.map((c) => <Pastille key={c} couleur="rouge">{libelle(c)}</Pastille>)}
      {cles.length > visibles.length && <Pastille couleur="rouge">+{cles.length - visibles.length}</Pastille>}
    </span>
  )
}

function CarteFiche({ f }: { f: Fiche }) {
  const naviguer = useNavigate()
  const lignesDetail = plats(f).slice(0, 4)
  return (
    <article
      className={`fiche-carte statut-${f.statut}`}
      onClick={() => naviguer(`/fiches/${f.id}`)}
      role="link"
      tabIndex={0}
      onKeyDown={(e) => { if (e.key === 'Enter') naviguer(`/fiches/${f.id}`) }}
    >
      <div className="fiche-heure">{f.heure}</div>
      <div className="fiche-corps">
        <div className="fiche-titre">
          <Link to={`/fiches/${f.id}`} onClick={(e) => e.stopPropagation()}>{f.client.nom}</Link>
          {f.espace !== 'salle' && <Pastille couleur="indigo">{f.espace}</Pastille>}
          {f.privatisation && <Pastille couleur="violet">{f.privatisation}</Pastille>}
        </div>
        <div className="fiche-repas"><Repas f={f} /></div>
        {lignesDetail.length > 0 && (
          <div className="fiche-lignes">
            {lignesDetail.map((l, i) => (
              <span key={i}><b>{l.quantite}</b> {l.libelle}</span>
            ))}
            {plats(f).length > lignesDetail.length && <span className="muet">+{plats(f).length - lignesDetail.length} autres</span>}
          </div>
        )}
        <div className="fiche-infos">
          <Pastille couleur={f.couleur_boissons}>{f.formule_boissons ?? 'boissons à définir'}</Pastille>
          <Allergenes cles={f.allergenes} />
        </div>
        {f.alertes.length > 0 && actif(f) && (
          <div className="fiche-alerte" title={f.alertes.join('\n')}>⚠ {f.alertes[0]}{f.alertes.length > 1 && ` (+${f.alertes.length - 1})`}</div>
        )}
      </div>
      <div className="fiche-cote">
        <div className="fiche-couverts"><b>{f.couverts}</b><small>couverts</small></div>
        <Statut statut={f.statut} libelle={f.statut_libelle} />
      </div>
    </article>
  )
}

export default function Fiches() {
  const { references } = useSession()
  const [params, setParams] = useSearchParams()
  const periode = params.get('periode') ?? 'a_venir'
  const espace = params.get('espace') ?? ''
  const statut = params.get('statut') ?? ''
  const jour = params.get('jour') ?? ''
  const aCompleter = params.get('a_completer') === '1'
  const [q, setQ] = useState(params.get('q') ?? '')

  const { donnees: fiches, erreur, chargement } = useCharger(
    () => api.get<Fiche[]>('/api/fiches', { periode, espace, statut, jour, q: params.get('q') ?? '' }),
    [periode, espace, statut, jour, params.get('q')],
  )

  const changer = (cle: string, valeur: string) => {
    const suivant = new URLSearchParams(params)
    if (valeur) suivant.set(cle, valeur)
    else suivant.delete(cle)
    setParams(suivant)
  }

  const toutes = fiches ?? []
  const visibles = aCompleter ? toutes.filter((f) => actif(f) && f.alertes.length > 0) : toutes
  const parJour = new Map<string, Fiche[]>()
  for (const f of visibles) parJour.set(f.date, [...(parJour.get(f.date) ?? []), f])

  const chiffres = {
    fiches: toutes.filter(actif).length,
    couverts: toutes.filter(actif).reduce((n, f) => n + f.couverts, 0),
    aCompleter: toutes.filter((f) => actif(f) && f.alertes.length > 0).length,
    brouillons: toutes.filter((f) => f.statut === 'brouillon').length,
  }

  return (
    <>
      <EnTete titre="Fiches">
        <Link className="bouton principal" to="/fiches/nouvelle">+ Nouvelle fiche</Link>
      </EnTete>

      <div className="chiffres">
        <div className="chiffre"><b>{chiffres.fiches}</b><span>fiches</span></div>
        <div className="chiffre"><b>{chiffres.couverts}</b><span>couverts</span></div>
        <button
          className={`chiffre cliquable${chiffres.aCompleter ? ' alerte' : ''}${aCompleter ? ' choisi' : ''}`}
          onClick={() => changer('a_completer', aCompleter ? '' : '1')}
          title="Afficher seulement les fiches à compléter"
        >
          <b>{chiffres.aCompleter}</b><span>à compléter</span>
        </button>
        <button
          className={`chiffre cliquable${statut === 'brouillon' ? ' choisi' : ''}`}
          onClick={() => changer('statut', statut === 'brouillon' ? '' : 'brouillon')}
          title="Afficher seulement les brouillons"
        >
          <b>{chiffres.brouillons}</b><span>brouillons</span>
        </button>
      </div>

      <div className="barre-filtres">
        <form className="recherche" onSubmit={(e) => { e.preventDefault(); changer('q', q.trim()) }}>
          <span aria-hidden>🔎</span>
          <input placeholder="Chercher un client, un contact…" value={q} onChange={(e) => setQ(e.target.value)}
                 onBlur={() => q.trim() !== (params.get('q') ?? '') && changer('q', q.trim())} />
        </form>
        <div className="segments" role="group" aria-label="Période">
          {PERIODES.map((p) => (
            <button key={p.cle} className={!jour && periode === p.cle ? 'choisi' : ''} onClick={() => {
              const suivant = new URLSearchParams(params)
              suivant.delete('jour')
              suivant.set('periode', p.cle)
              setParams(suivant)
            }}>{p.libelle}</button>
          ))}
          <button className={jour === aujourdhui() ? 'choisi' : ''} onClick={() => changer('jour', jour === aujourdhui() ? '' : aujourdhui())}>
            Aujourd'hui
          </button>
        </div>
        <input type="date" value={jour} onChange={(e) => changer('jour', e.target.value)} title="Un jour précis" />
      </div>

      <div className="puces-filtres">
        <span className="muet">Statut</span>
        <button className={`puce${statut === '' ? ' active' : ''}`} onClick={() => changer('statut', '')}>Tous</button>
        {references?.statuts_fiche.map((s) => (
          <button key={s.cle} className={`puce${statut === s.cle ? ' active' : ''}`} onClick={() => changer('statut', statut === s.cle ? '' : s.cle)}>
            {s.libelle}
          </button>
        ))}
        <span className="muet espace-gauche">Espace</span>
        <button className={`puce${espace === '' ? ' active' : ''}`} onClick={() => changer('espace', '')}>Tous</button>
        {references?.espaces.map((e) => (
          <button key={e} className={`puce${espace === e ? ' active' : ''}`} onClick={() => changer('espace', espace === e ? '' : e)}>{e}</button>
        ))}
      </div>

      <Erreur message={erreur} />
      <Chargement actif={chargement && !fiches} />
      {fiches && visibles.length === 0 && (
        <div className="vide">
          <p>{aCompleter ? 'Aucune fiche à compléter. 👍' : 'Aucune fiche pour ces filtres.'}</p>
          <Link className="bouton" to="/fiches/nouvelle">Créer une fiche</Link>
        </div>
      )}

      {[...parJour.entries()].map(([date, liste]) => {
        const repere = reperage(date)
        const couverts = liste.filter(actif).reduce((n, f) => n + f.couverts, 0)
        return (
          <section key={date} className="journee">
            <header className="journee-tete">
              <div>
                <h2>{dateLongue(date)}</h2>
                {repere && <span className={`repere ${repere.classe}`}>{repere.texte}</span>}
              </div>
              <div className="journee-total">
                <span><b>{liste.filter(actif).length}</b> fiche{liste.filter(actif).length > 1 ? 's' : ''}</span>
                <span><b>{couverts}</b> couverts</span>
                <button onClick={() => ouvrirPdf(`/api/jour/${date}/pdf`)}>PDF du jour</button>
              </div>
            </header>
            <div className="journee-fiches">
              {liste.map((f) => <CarteFiche key={f.id} f={f} />)}
            </div>
          </section>
        )
      })}
    </>
  )
}
