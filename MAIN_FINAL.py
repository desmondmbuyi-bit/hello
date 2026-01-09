import sqlite3
import tkinter as tk # Gardé pour les constantes (tk.END, tk.NO)
from tkinter import ttk, messagebox
from datetime import datetime
import customtkinter as ctk 
# Imports pour la génération de PDF
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
import os
import shutil
from tkinter import messagebox, filedialog # Ajouter filedialog

# --- PARTIE 1 : GESTION DE LA BASE DE DONNÉES (Le Backend) ---
class GestionBaseDeDonnees:
    def __init__(self, db_name="mon_magasin.db"):
        self.db_name = db_name
        self.conn = sqlite3.connect(db_name)
        self.cursor = self.conn.cursor()
        self.creer_tables()
        self.initialiser_utilisateurs() 

    def creer_tables(self):
        # Table des produits (Stock)
        # PRIX EST MAINTENANT EN CDF
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS produits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nom TEXT NOT NULL,
                prix REAL NOT NULL,
                quantite INTEGER NOT NULL,
                categorie TEXT DEFAULT 'Général' -- MODIF: AJOUT de la colonne Catégorie
            )
        """)
        # Table des ventes (Historique)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS ventes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                produit_id INTEGER,
                quantite INTEGER,
                date_vente TEXT,
                FOREIGN KEY(produit_id) REFERENCES produits(id)
            )
        """)
        # Table des mouvements de stock (Journal d'inventaire)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS journal_stock (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                produit_id INTEGER,
                quantite_ajoutee INTEGER NOT NULL,
                date_entree TEXT NOT NULL,
                FOREIGN KEY(produit_id) REFERENCES produits(id)
            )
        """)
        # Table des utilisateurs (pour la connexion et les rôles)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role TEXT NOT NULL
            )
        """)
        # Table de configuration (pour le taux de change)
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS configuration (
            cle TEXT PRIMARY KEY,
            valeur TEXT
            )
        """)
        self.conn.commit()

    def initialiser_utilisateurs(self):
        # Utilisateurs de test : Gérant et Vendeur
        self.ajouter_utilisateur_initial("gérant", "admin123", "Gérant")
        self.ajouter_utilisateur_initial("vendeur", "sale456", "Vendeur")
        self.ajouter_configuration_initiale("taux_usd_cdf", "2750") # Taux de base initial (CDF par USD)
        
    def ajouter_configuration_initiale(self, cle, valeur):
        try:
            self.cursor.execute("INSERT INTO configuration (cle, valeur) VALUES (?, ?)", 
                            (cle, valeur))
            self.conn.commit()
        except sqlite3.IntegrityError:
            pass # La clé de configuration existe déjà

    def ajouter_utilisateur_initial(self, username, password, role):
        try:
            self.cursor.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)", 
                                (username, password, role))
            self.conn.commit()
        except sqlite3.IntegrityError:
            pass # L'utilisateur existe déjà

    def verifier_utilisateur(self, username, password):
        self.cursor.execute("SELECT id, role FROM users WHERE username = ? AND password = ?", (username, password))
        resultat = self.cursor.fetchone()
        if resultat:
            return resultat # Retourne (id, role)
        return None

    def ajouter_produit(self, nom, prix, quantite, categorie="Général"): # MODIF: Ajout de categorie
        self.cursor.execute("INSERT INTO produits (nom, prix, quantite, categorie) VALUES (?, ?, ?, ?)", 
                            (nom, prix, quantite, categorie)) # MODIF: Ajout de categorie
        self.conn.commit()

    def enregistrer_entree_stock(self, produit_id, quantite_ajoutee):
        """Ajoute une quantité au stock et enregistre le mouvement."""
        if quantite_ajoutee <= 0:
            return False, "La quantité ajoutée doit être positive."
            
        self.cursor.execute("SELECT quantite FROM produits WHERE id = ?", (produit_id,))
        resultat = self.cursor.fetchone()
        
        if not resultat:
            return False, "Produit introuvable."
            
        stock_actuel = resultat[0]
        nouveau_stock = stock_actuel + quantite_ajoutee
        
        # 1. Mise à jour du stock total dans la table produits
        self.cursor.execute("UPDATE produits SET quantite = ? WHERE id = ?", (nouveau_stock, produit_id))
        
        # 2. Enregistrement dans le journal de stock
        date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.cursor.execute("INSERT INTO journal_stock (produit_id, quantite_ajoutee, date_entree) VALUES (?, ?, ?)", 
                            (produit_id, quantite_ajoutee, date))
                            
        self.conn.commit()
        return True, "Entrée de stock enregistrée."

    def recuperer_journal_stock(self, date_debut=None, date_fin=None): # MODIF: Ajout de filtres
        """Récupère tous les mouvements d'entrée de stock, avec filtres optionnels."""
        query = """
            SELECT
                j.date_entree,
                p.nom,
                j.quantite_ajoutee
            FROM journal_stock j
            JOIN produits p ON j.produit_id = p.id
        """
        params = []
        conditions = []
        
        # Construction dynamique des filtres de dates
        if date_debut:
            conditions.append("j.date_entree >= ?")
            params.append(date_debut + " 00:00:00")
        if date_fin:
            conditions.append("j.date_entree <= ?")
            params.append(date_fin + " 23:59:59")
        
        if conditions:
            query += " WHERE " + " AND ".join(conditions) # AJOUT
            
        query += " ORDER BY j.date_entree DESC"
        
        self.cursor.execute(query, params) # MODIF: Passage des paramètres
        # Résultat: (date_entree, nom_produit, quantite_ajoutee)
        return self.cursor.fetchall()

    def recuperer_categories(self):
        """Récupère la liste de toutes les catégories uniques."""
        # AJOUT
        self.cursor.execute("SELECT DISTINCT categorie FROM produits WHERE categorie IS NOT NULL AND categorie != '' ORDER BY categorie ASC")
        # Le résultat est une liste de tuples (categorie,). On extrait la chaîne.
        return [row[0] for row in self.cursor.fetchall()]

    def recuperer_produits(self, categorie_filtre=None): # MODIF: Ajout de categorie_filtre
        """Récupère la liste des produits, optionnellement filtrée par catégorie."""
        query = "SELECT * FROM produits"
        params = []
        
        # Le filtre est géré entièrement au niveau du frontend maintenant
        # car on a besoin de tous les produits pour l'affichage gérant et les détails
        # du panier, mais on garde la signature pour l'éventuelle évolution future.
        self.cursor.execute(query, params)
        # Résultat: (id, nom, prix, quantite, categorie)
        return self.cursor.fetchall()

    def faire_une_vente(self, produit_id, quantite_demandee):
        """
        Effectue une vente pour un seul produit. 
        Cette méthode sera appelée en boucle pour chaque article du panier.
        """
        # Logique de transaction (vérification et soustraction du stock)
        self.cursor.execute("SELECT quantite FROM produits WHERE id = ?", (produit_id,))
        resultat = self.cursor.fetchone()
        
        if resultat:
            stock_actuel = resultat[0]
            if stock_actuel >= quantite_demandee:
                # Soustraction du stock
                nouveau_stock = stock_actuel - quantite_demandee
                self.cursor.execute("UPDATE produits SET quantite = ? WHERE id = ?", (nouveau_stock, produit_id))
                
                # Enregistrement de la vente
                date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self.cursor.execute("INSERT INTO ventes (produit_id, quantite, date_vente) VALUES (?, ?, ?)", 
                                    (produit_id, quantite_demandee, date))
                
                # Commit de la transaction (IMPORTANT)
                self.conn.commit() 
                return True, "Vente réussie !"
            else:
                return False, "Erreur : Stock insuffisant."
        return False, "Erreur : Produit introuvable."
        
    def recuperer_ventes(self, date_debut=None, date_fin=None):
        """
        Récupère l'historique des ventes avec les détails des produits et les totaux en CDF.
        """
        query = """
            SELECT
                v.date_vente,
                p.nom,
                v.quantite,
                p.prix,  -- Prix unitaire en CDF (devise de base)
                (v.quantite * p.prix) AS total_vente -- Total de la vente en CDF
            FROM ventes v
            JOIN produits p ON v.produit_id = p.id
        """
        params = []
        conditions = []

        # Construction dynamique des filtres de dates
        if date_debut:
            conditions.append("v.date_vente >= ?")
            params.append(date_debut + " 00:00:00")
        if date_fin:
            conditions.append("v.date_vente <= ?")
            params.append(date_fin + " 23:59:59")
        
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        
        query += " ORDER BY v.date_vente DESC"

        self.cursor.execute(query, params)
        # Le résultat contient : (date, nom_produit, quantité, prix_unitaire_cdf, total_vente_cdf)
        return self.cursor.fetchall()
        
    def modifier_produit(self, produit_id, nom, prix, quantite, categorie="Général"): # MODIF: Ajout de categorie
        self.cursor.execute("UPDATE produits SET nom = ?, prix = ?, quantite = ?, categorie = ? WHERE id = ?", 
                            (nom, prix, quantite, categorie, produit_id)) # MODIF: Ajout de categorie
        self.conn.commit()
        
    def supprimer_produit(self, produit_id):
        self.cursor.execute("DELETE FROM produits WHERE id = ?", (produit_id,))
        self.conn.commit()
        
    def creer_utilisateur(self, username, password, role):
        try:
            self.cursor.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)", 
                                (username, password, role))
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False 
            
    def recuperer_utilisateurs(self):
        self.cursor.execute("SELECT id, username, role FROM users")
        return self.cursor.fetchall()
        
    def sauvegarder_bdd(self):
        """Crée une copie de la base de données principale dans un dossier 'backups'."""
        try:
            backup_dir = "backups"
            if not os.path.exists(backup_dir):
                os.makedirs(backup_dir)
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = os.path.join(backup_dir, f"backup_{timestamp}.db")
            
            backup_conn = sqlite3.connect(backup_path)
            self.conn.backup(backup_conn)
            backup_conn.close()
            
            return backup_path
        except Exception as e:
            print(f"Erreur de sauvegarde: {e}")
            return None

    def restaurer_bdd(self, backup_filepath):
        """Restaure la base de données principale à partir d'un fichier de sauvegarde."""
        try:
            self.conn.close()
            shutil.copyfile(backup_filepath, self.db_name)
            self.conn = sqlite3.connect(self.db_name)
            self.cursor = self.conn.cursor()
            
            return True
        except Exception as e:
            print(f"Erreur de restauration: {e}")
            try:
                self.conn = sqlite3.connect(self.db_name)
                self.cursor = self.conn.cursor()
            except:
                pass 
            return False
            
    def supprimer_utilisateur(self, user_id):
        if user_id == 1:
            return False 
        
        self.cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
        self.conn.commit()
        return True
        
    def changer_mot_de_passe(self, user_id, new_password):
        self.cursor.execute("UPDATE users SET password = ? WHERE id = ?", 
                            (new_password, user_id))
        self.conn.commit()
        
    def get_taux_usd_cdf(self):
        """Récupère le taux de change (CDF par 1 USD)."""
        self.cursor.execute("SELECT valeur FROM configuration WHERE cle = 'taux_usd_cdf'")
        resultat = self.cursor.fetchone()
        
        try:
            # Retourne le nombre de CDF pour 1 USD. 
            return float(resultat[0]) if resultat and resultat[0] else 2750.0
        except (IndexError, TypeError, ValueError):
            return 2750.0 # Taux par défaut de secours

    def set_taux_usd_cdf(self, nouveau_taux):
        """Met à jour le taux de change USD vers CDF."""
        self.cursor.execute("""
            INSERT OR REPLACE INTO configuration (cle, valeur) VALUES ('taux_usd_cdf', ?)
        """, (str(nouveau_taux),))
        self.conn.commit()


# --- PARTIE 2 : INTERFACE GRAPHIQUE ET RBAC (Frontend) ---
class ApplicationEcommerce:
    def __init__(self, root):
        self.db = GestionBaseDeDonnees()
        self.root = root
        
        # Initialisation des variables de session
        self.current_user_id = None 
        self.current_user_role = None 
        
        # Initialisation du Panier
        self.panier = {} # {produit_id: quantite}
        # Dictionnaire pour stocker les détails du produit {id: {nom, prix, stock, categorie}}
        self.produits_details = {} 
        self.current_category_filter = "Toutes les catégories" # AJOUT: Filtre de catégorie actif
        
        # Configuration initiale de la fenêtre de connexion
        self.root.title("Logiciel Gestion E-Commerce (Connexion)")
        self.root.geometry("400x350") 
        self.root.resizable(False, False)

        self.main_frame = ctk.CTkFrame(self.root)
        self.main_frame.pack(fill="both", expand=True)

        self.montrer_page_connexion()
    

    # --- Connexion et RBAC ---

    def montrer_page_connexion(self):
        for widget in self.main_frame.winfo_children():
            widget.destroy()

        self.root.geometry("400x350")
        self.root.title("Connexion")
        
        ctk.CTkLabel(self.main_frame, text="CONNEXION REQUISE", font=("Arial", 20, "bold")).pack(pady=25)

        ctk.CTkLabel(self.main_frame, text="Nom d'utilisateur:").pack(pady=5)
        self.login_user_entry = ctk.CTkEntry(self.main_frame, width=250)
        self.login_user_entry.pack(pady=5)
        # La zone de saisie est vide par défaut (Sécurité)

        ctk.CTkLabel(self.main_frame, text="Mot de passe:").pack(pady=5)
        self.login_pass_entry = ctk.CTkEntry(self.main_frame, width=250, show="*")
        self.login_pass_entry.pack(pady=5)
        # La zone de saisie est vide par défaut (Sécurité)

        ctk.CTkButton(self.main_frame, text="Se Connecter", command=self.action_connexion).pack(pady=30)

    def action_connexion(self):
        user = self.login_user_entry.get()
        password = self.login_pass_entry.get()
        
        login_result = self.db.verifier_utilisateur(user, password)
        
        if login_result:
            user_id, role = login_result
            
            self.current_user_id = user_id 
            self.current_user_role = role
            
            self.montrer_interfaces_principales(role)
        else:
            messagebox.showerror("Erreur de Connexion", "Nom d'utilisateur ou mot de passe incorrect.")

    def montrer_interfaces_principales(self, role):
        for widget in self.main_frame.winfo_children():
            widget.destroy()
            
        self.root.geometry("800x600")
        self.root.resizable(True, True)
        self.root.title(f"Application E-Commerce | Rôle: {role}")

        self.tab_view = ctk.CTkTabview(self.main_frame)
        self.tab_view.pack(fill="both", expand=True, padx=10, pady=10)

        self.tab_vendeur_frame = self.tab_view.add("Espace Vendeur (Caisse)")
        self.setup_interface_vendeur(self.tab_vendeur_frame)

        if role == "Gérant":
            self.tab_gerant_frame = self.tab_view.add("Espace Gérant (Stock)")
            self.tab_historique_frame = self.tab_view.add("Historique des Ventes")
            self.tab_journal_stock_frame = self.tab_view.add("Journal de Stock (Entrées)")
            self.tab_admin_frame = self.tab_view.add("Administration") 

            self.setup_interface_gerant(self.tab_gerant_frame)
            self.setup_interface_historique(self.tab_historique_frame)
            self.setup_interface_journal_stock(self.tab_journal_stock_frame)
            self.setup_interface_administration(self.tab_admin_frame)

            self.tab_view.set("Espace Gérant (Stock)")
        else:
            self.tab_view.set("Espace Vendeur (Caisse)")

        self.rafraichir_listes() 
        
    # --- Vues Spécifiques ---

    def setup_interface_gerant(self, tab_frame):
        self.produit_selectionne_id = None

        # --- A. FRAME MODIFICATION PRODUIT (AJOUT/MODIF/SUPPRESSION) ---
        input_frame = ctk.CTkFrame(tab_frame)
        input_frame.pack(pady=20, padx=20, fill="x")

        ctk.CTkLabel(input_frame, text="GESTION DES ARTICLES (Ajout / Modification Totale)", font=("Arial", 18, "bold")).grid(row=0, column=0, columnspan=4, pady=10)

        ctk.CTkLabel(input_frame, text="Nom du produit :").grid(row=1, column=0, padx=10, pady=5, sticky="w")
        self.entry_nom = ctk.CTkEntry(input_frame, width=150)
        self.entry_nom.grid(row=1, column=1, padx=10, pady=5, sticky="ew")

        # QUANTITÉ EST ICI LE TOTAL À DÉFINIR
        ctk.CTkLabel(input_frame, text="Quantité (Stock Total) :").grid(row=1, column=2, padx=10, pady=5, sticky="w")
        self.entry_qty = ctk.CTkEntry(input_frame, width=150)
        self.entry_qty.grid(row=1, column=3, padx=10, pady=5, sticky="ew")

        # LIBELLÉ PRIX EN CDF
        ctk.CTkLabel(input_frame, text="Prix (FC - Réel) :").grid(row=2, column=0, padx=10, pady=5, sticky="w")
        self.entry_prix = ctk.CTkEntry(input_frame, width=150)
        self.entry_prix.grid(row=2, column=1, padx=10, pady=5, sticky="ew")

        # NOUVEAU: Champ Catégorie
        ctk.CTkLabel(input_frame, text="Catégorie :").grid(row=2, column=2, padx=10, pady=5, sticky="w")
        self.entry_categorie = ctk.CTkEntry(input_frame, width=150)
        self.entry_categorie.grid(row=2, column=3, padx=10, pady=5, sticky="ew")
        self.entry_categorie.insert(0, "Général") # Valeur par défaut
        
        btn_add = ctk.CTkButton(input_frame, text="➕ Ajouter un Nouveau", 
                                command=self.action_ajouter_produit, 
                                fg_color="#3B8EDC", hover_color="#36719F")
        btn_add.grid(row=3, column=0, columnspan=2, pady=15, padx=10, sticky="ew")

        btn_modify = ctk.CTkButton(input_frame, text="✏️ Modifier la Sélection (Total)", 
                                command=self.action_modifier_produit,
                                fg_color="#F39C12", hover_color="#D68910")
        btn_modify.grid(row=3, column=2, pady=15, padx=10, sticky="ew")
        
        btn_delete = ctk.CTkButton(input_frame, text="🗑️ Supprimer la Sélection", 
                                command=self.action_supprimer_produit,
                                fg_color="#C0392B", hover_color="#A93226")
        btn_delete.grid(row=3, column=3, pady=15, padx=10, sticky="ew")
        
        input_frame.grid_columnconfigure((1, 3), weight=1)

        # --- B. NOUVELLE SECTION : RÉCEPTION DE STOCK ---
        separator_stock = ctk.CTkFrame(tab_frame, height=2, fg_color="gray")
        separator_stock.pack(fill="x", padx=20, pady=20)
        
        replenishment_frame = ctk.CTkFrame(tab_frame)
        replenishment_frame.pack(pady=10, padx=20, fill="x")

        ctk.CTkLabel(replenishment_frame, text="RÉCEPTION DE STOCK (Ajout d'unités au stock actuel)", font=("Arial", 16, "bold")).grid(row=0, column=0, columnspan=4, pady=10)
        
        ctk.CTkLabel(replenishment_frame, text="Article :").grid(row=1, column=0, padx=10, pady=5, sticky="w")
        self.combo_replenish_product = ctk.CTkComboBox(replenishment_frame, values=["Chargement..."], width=250)
        self.combo_replenish_product.grid(row=1, column=1, padx=10, pady=5, sticky="ew")

        ctk.CTkLabel(replenishment_frame, text="Quantité ajoutée :").grid(row=1, column=2, padx=10, pady=5, sticky="w")
        self.entry_replenish_qty = ctk.CTkEntry(replenishment_frame, width=100)
        self.entry_replenish_qty.grid(row=1, column=3, padx=10, pady=5, sticky="ew")
        self.entry_replenish_qty.insert(0, "1")

        btn_replenish = ctk.CTkButton(replenishment_frame, text="🚚 Valider l'Entrée de Stock", 
                                command=self.action_entree_stock, 
                                fg_color="#1E8449", hover_color="#145A32")
        btn_replenish.grid(row=2, column=0, columnspan=4, pady=15, padx=10, sticky="ew")
        
        replenishment_frame.grid_columnconfigure(1, weight=1)


        # --- C. AFFICHAGE DU STOCK ACTUEL ---
        ctk.CTkLabel(tab_frame, text="STOCK ACTUEL (Cliquez pour modifier/supprimer)", font=("Arial", 16, "bold")).pack(pady=(10, 5))
        
        tree_frame = ctk.CTkFrame(tab_frame)
        tree_frame.pack(pady=10, padx=20, fill="both", expand=True)

        # MODIF: Ajout de la colonne Catégorie
        self.tree_stock = ttk.Treeview(tree_frame, columns=("ID", "Nom", "Catégorie", "Prix", "Qté"), show='headings')
        self.tree_stock.heading("ID", text="ID", anchor="center")
        self.tree_stock.heading("Nom", text="Nom", anchor="center")
        self.tree_stock.heading("Catégorie", text="Catégorie", anchor="center") # NOUVEAU
        # LIBELLÉ PRIX EN CDF
        self.tree_stock.heading("Prix", text="Prix (FC)", anchor="center") 
        self.tree_stock.heading("Qté", text="Quantité", anchor="center")
        
        self.tree_stock.column("ID", width=50, stretch=tk.NO)
        self.tree_stock.column("Nom", width=150, stretch=tk.YES)
        self.tree_stock.column("Catégorie", width=100, stretch=tk.NO) # NOUVEAU
        self.tree_stock.column("Prix", width=80, stretch=tk.NO)
        self.tree_stock.column("Qté", width=80, stretch=tk.NO)
        
        self.tree_stock.pack(side="left", fill="both", expand=True)

        scrollbar = ctk.CTkScrollbar(tree_frame, command=self.tree_stock.yview)
        scrollbar.pack(side="right", fill="y")
        self.tree_stock.configure(yscrollcommand=scrollbar.set)
        
        self.tree_stock.bind('<<TreeviewSelect>>', self.selectionner_produit)

    def action_entree_stock(self):
        try:
            selection_complete = self.combo_replenish_product.get()
            
            if "AUCUN PRODUIT" in selection_complete or "Chargement" in selection_complete:
                messagebox.showwarning("Erreur", "Veuillez sélectionner un produit.")
                return

            prod_id_str = selection_complete.split(' | ')[0]
            prod_id = int(prod_id_str) 
            qty_ajoutee = int(self.entry_replenish_qty.get())

            if qty_ajoutee <= 0:
                messagebox.showwarning("Attention", "La quantité ajoutée doit être positive.")
                return
            
            success, message = self.db.enregistrer_entree_stock(prod_id, qty_ajoutee)
            
            if success:
                messagebox.showinfo("Succès", message)
                self.entry_replenish_qty.delete(0, tk.END)
                self.entry_replenish_qty.insert(0, "1")
                self.rafraichir_listes() 
                if hasattr(self, 'tree_journal_stock'):
                    self.rafraichir_journal_stock() 
            else:
                messagebox.showerror("Erreur", message)

        except ValueError:
            messagebox.showerror("Erreur", "Veuillez entrer une quantité valide.")
        except Exception:
             messagebox.showerror("Erreur", "Impossible de valider l'entrée de stock.")
        
    def setup_interface_vendeur(self, tab_frame):
        # AJOUT: Nouvelle frame pour le filtre de catégorie
        filter_category_frame = ctk.CTkFrame(tab_frame)
        filter_category_frame.pack(pady=(20, 10), padx=20, fill="x")
        
        ctk.CTkLabel(filter_category_frame, text="Filtrer par Catégorie :", font=("Arial", 14)).grid(row=0, column=0, padx=10, pady=5, sticky="w")
        
        self.combo_category_filter = ctk.CTkComboBox(filter_category_frame, 
                                                     values=["Toutes les catégories"], 
                                                     command=self.action_selectionner_categorie, # NOUVELLE ACTION
                                                     width=200)
        self.combo_category_filter.grid(row=0, column=1, padx=10, pady=5, sticky="ew")
        self.combo_category_filter.set("Toutes les catégories")
        filter_category_frame.grid_columnconfigure(1, weight=1)
        
        # --- A. FRAME D'AJOUT D'ARTICLE AU PANIER ---
        add_frame = ctk.CTkFrame(tab_frame)
        add_frame.pack(pady=(10, 10), padx=20, fill="x") # MODIF pady

        ctk.CTkLabel(add_frame, text="AJOUTER UN ARTICLE AU PANIER", font=("Arial", 16, "bold")).grid(row=0, column=0, columnspan=4, pady=(5, 10))

        # 1. Combobox de sélection de produit
        ctk.CTkLabel(add_frame, text="Produit :").grid(row=1, column=0, padx=10, pady=5, sticky="w")
        self.combobox_produits = ctk.CTkComboBox(add_frame, values=["Veuillez ajouter des produits"], width=300)
        self.combobox_produits.grid(row=1, column=1, padx=10, pady=5, sticky="ew")

        # 2. Champ Quantité
        ctk.CTkLabel(add_frame, text="Quantité :").grid(row=1, column=2, padx=10, pady=5, sticky="w")
        self.entry_vente_qty = ctk.CTkEntry(add_frame, width=80)
        self.entry_vente_qty.grid(row=1, column=3, padx=10, pady=5, sticky="ew")
        self.entry_vente_qty.insert(0, "1")

        # 3. Bouton Ajouter
        btn_add_to_cart = ctk.CTkButton(add_frame, text="🛒 Ajouter au Panier", 
                                        fg_color="#3B8EDC", hover_color="#36719F",
                                        command=self.action_ajouter_au_panier)
        btn_add_to_cart.grid(row=2, column=0, columnspan=4, pady=10, padx=10, sticky="ew")
        
        add_frame.grid_columnconfigure(1, weight=1)
        add_frame.grid_columnconfigure(3, weight=0) 

        # --- B. FRAME DU PANIER (Treeview) ---
        ctk.CTkLabel(tab_frame, text="PANIER ACTUEL", font=("Arial", 16, "bold")).pack(pady=(20, 5))
        
        # Panier Treeview
        tree_frame = ctk.CTkFrame(tab_frame)
        tree_frame.pack(pady=10, padx=20, fill="both", expand=True)
        
        self.tree_panier = ttk.Treeview(tree_frame, columns=("ID", "Nom", "Qté", "Prix U", "Total"), show='headings')
        self.tree_panier.heading("ID", text="ID", anchor="center")
        self.tree_panier.heading("Nom", text="Produit", anchor="center")
        self.tree_panier.heading("Qté", text="Qté", anchor="center")
        self.tree_panier.heading("Prix U", text="Prix U (FC)", anchor="center")
        self.tree_panier.heading("Total", text="Total (FC)", anchor="center") 
        
        self.tree_panier.column("ID", width=50, stretch=tk.NO)
        self.tree_panier.column("Nom", width=200, stretch=tk.YES)
        self.tree_panier.column("Qté", width=70, stretch=tk.NO)
        self.tree_panier.column("Prix U", width=100, stretch=tk.NO)
        self.tree_panier.column("Total", width=100, stretch=tk.NO)
        
        self.tree_panier.pack(side="left", fill="both", expand=True)

        scrollbar = ctk.CTkScrollbar(tree_frame, command=self.tree_panier.yview)
        scrollbar.pack(side="right", fill="y")
        self.tree_panier.configure(yscrollcommand=scrollbar.set)
        
        # Affichage du total en temps réel
        self.panier_total_label = ctk.CTkLabel(tab_frame, text="TOTAL GÉNÉRAL : 0 FC", font=("Arial", 16, "bold"))
        self.panier_total_label.pack(pady=(5, 10))

        # Boutons Panier
        btn_frame = ctk.CTkFrame(tab_frame)
        btn_frame.pack(pady=(5, 20), padx=20, fill="x")

        btn_remove = ctk.CTkButton(btn_frame, text="🗑️ Retirer la Sélection du Panier", 
                                   command=self.action_retirer_du_panier,
                                   fg_color="#C0392B", hover_color="#A93226")
        btn_remove.pack(side="left", padx=10, fill="x", expand=True)

        btn_checkout = ctk.CTkButton(btn_frame, text="✅ Valider la Vente (Paiement)", 
                                     command=self.action_valider_panier,
                                     fg_color="#2ECC71", hover_color="#27AE60")
        btn_checkout.pack(side="right", padx=10, fill="x", expand=True)

    def action_selectionner_categorie(self, new_category):
        """Mise à jour du filtre de catégorie et rafraîchissement des produits de vente."""
        # NOUVELLE MÉTHODE
        self.current_category_filter = new_category
        self.rafraichir_listes() # Rafraîchissement qui va appliquer le filtre au combobox_produits

    def action_ajouter_produit(self):
        try:
            nom = self.entry_nom.get()
            prix = float(self.entry_prix.get())
            qty = int(self.entry_qty.get())
            categorie = self.entry_categorie.get().strip() # NOUVEAU
            if not categorie: categorie = "Général"
            
            self.db.ajouter_produit(nom, prix, qty, categorie) # MODIF: Passage de catégorie
            messagebox.showinfo("Succès", "Produit ajouté !")
            self.rafraichir_listes()
            self.entry_nom.delete(0, tk.END)
            self.entry_prix.delete(0, tk.END)
            self.entry_qty.delete(0, tk.END)
            self.entry_categorie.delete(0, tk.END) # NOUVEAU
            self.entry_categorie.insert(0, "Général")

        except ValueError:
            messagebox.showerror("Erreur", "Vérifiez que le prix et la quantité sont des nombres.")
    
    def selectionner_produit(self, event):
        selected_item = self.tree_stock.focus()
        if selected_item:
            # MODIF: La liste des valeurs contient maintenant la catégorie
            values = self.tree_stock.item(selected_item, 'values')
            self.produit_selectionne_id = int(values[0])
            
            # values: (ID, Nom, Catégorie, Prix, Qté)
            nom = values[1]
            categorie = values[2] # Nouvel index
            prix = values[3] 
            qty = values[4] 
            
            self.entry_nom.delete(0, tk.END)
            self.entry_nom.insert(0, nom)
            self.entry_prix.delete(0, tk.END)
            # Enlever le ' FC' pour l'édition
            self.entry_prix.insert(0, str(prix).replace(' FC', '').replace(',', '.')) 
            self.entry_qty.delete(0, tk.END)
            self.entry_qty.insert(0, qty)
            self.entry_categorie.delete(0, tk.END) # NOUVEAU
            self.entry_categorie.insert(0, categorie) # NOUVEAU

    def action_modifier_produit(self):
        if not hasattr(self, 'produit_selectionne_id') or self.produit_selectionne_id is None:
            messagebox.showwarning("Modification", "Veuillez sélectionner un produit dans la liste à modifier.")
            return 
            
        try:
            prod_id = self.produit_selectionne_id
            nom = self.entry_nom.get()
            prix = float(self.entry_prix.get())
            qty = int(self.entry_qty.get())
            categorie = self.entry_categorie.get().strip() # NOUVEAU
            if not categorie: categorie = "Général"
            
            # C'est la nouvelle quantité TOTALE
            if not nom or prix < 0 or qty < 0:
                messagebox.showerror("Erreur", "Veuillez remplir tous les champs correctement.")
                return 
                
            self.db.modifier_produit(prod_id, nom, prix, qty, categorie) # MODIF: Passage de catégorie
            messagebox.showinfo("Succès", f"Produit ID {prod_id} modifié avec succès (Stock Total mis à jour).")
            self.produit_selectionne_id = None
            self.entry_nom.delete(0, tk.END)
            self.entry_prix.delete(0, tk.END)
            self.entry_qty.delete(0, tk.END)
            self.entry_categorie.delete(0, tk.END) # NOUVEAU
            self.entry_categorie.insert(0, "Général")
            self.rafraichir_listes()
            
        except ValueError:
            messagebox.showerror("Erreur", "Veuillez entrer des valeurs numériques valides pour le Prix et la Quantité.")
            
    def action_supprimer_produit(self):
        if not hasattr(self, 'produit_selectionne_id') or self.produit_selectionne_id is None:
            messagebox.showwarning("Suppression", "Veuillez sélectionner un produit dans la liste à supprimer.")
            return 
            
        prod_id = self.produit_selectionne_id
        nom_produit = self.entry_nom.get()
        confirmation = messagebox.askyesno(
            "Confirmation de Suppression",
            f"Êtes-vous sûr de vouloir supprimer définitivement le produit ID {prod_id} ({nom_produit}) ? Cette action est irréversible."
        )
        
        if confirmation:
            self.db.supprimer_produit(prod_id)
            messagebox.showinfo("Succès", f"Produit ID {prod_id} supprimé.")
            self.produit_selectionne_id = None
            self.entry_nom.delete(0, tk.END)
            self.entry_prix.delete(0, tk.END)
            self.entry_qty.delete(0, tk.END)
            self.entry_categorie.delete(0, tk.END) # NOUVEAU
            self.entry_categorie.insert(0, "Général")
            self.rafraichir_listes()
            
    def rafraichir_listes(self):
        """
        Rafraîchit l'affichage du stock (Gérant), les comboboxes (Gérant/Vendeur) et le panier.
        Le filtre de catégorie est appliqué ici pour la liste de vente.
        """
        # 1. Récupérer TOUS les produits pour la gestion du stock et les détails
        produits = self.db.recuperer_produits() 
        
        # 2. Mise à jour de self.produits_details (pour le panier)
        self.produits_details.clear()
        
        # Effacer les Treeviews
        if hasattr(self, 'tree_stock'):
            for row in self.tree_stock.get_children():
                self.tree_stock.delete(row)
        
        # Préparation des comboboxes
        produits_vendeur_combobox_values = ["AUCUN PRODUIT DISPONIBLE"]
        produits_replenish_combobox_values = ["AUCUN PRODUIT"]
        
        # Liste pour le ComboBox Vendeur (filtrée par catégorie)
        produits_vendeur_liste = []
        
        # 3. Remplissage des données
        for produit in produits:
            # produit = (id, nom, prix, quantite, categorie)
            prod_id, nom, prix, quantite, categorie = produit 
            
            # Mise à jour du détail pour le panier (Vendeur)
            self.produits_details[prod_id] = {
                'nom': nom, 
                'prix': prix, 
                'stock': quantite,
                'categorie': categorie # NOUVEAU
            }
            
            # Mise à jour de l'affichage Gérant (Treeview Stock)
            if hasattr(self, 'tree_stock'):
                # MODIF: Ajouter la catégorie
                self.tree_stock.insert("", tk.END, values=(prod_id, nom, categorie, f"{prix:.0f} FC", quantite)) 

            # Remplissage du ComboBox de Réception de Stock (Gérant)
            produits_replenish_combobox_values.append(f"{prod_id} | {nom}")

            # Remplissage de la liste Vendeur (application du filtre de catégorie)
            if self.current_category_filter == "Toutes les catégories" or categorie == self.current_category_filter:
                produits_vendeur_liste.append(f"{prod_id} | {nom} ({quantite} en stock)")
        
        # Remplissage du ComboBox Réception de Stock (Gérant)
        if hasattr(self, 'combo_replenish_product'):
            if len(produits_replenish_combobox_values) > 1:
                self.combo_replenish_product.configure(values=produits_replenish_combobox_values[1:])
                self.combo_replenish_product.set(produits_replenish_combobox_values[1])
            else:
                self.combo_replenish_product.configure(values=["AUCUN PRODUIT"])
                self.combo_replenish_product.set("AUCUN PRODUIT")

        # Remplissage du ComboBox Vendeur (Caisse)
        if hasattr(self, 'combobox_produits'):
            if produits_vendeur_liste:
                self.combobox_produits.configure(values=produits_vendeur_liste)
                self.combobox_produits.set(produits_vendeur_liste[0])
            else:
                self.combobox_produits.configure(values=produits_vendeur_combobox_values)
                self.combobox_produits.set(produits_vendeur_combobox_values[0])
                
        # 4. Mise à jour des catégories (pour le ComboBox Catégories Vendeur)
        if hasattr(self, 'combo_category_filter'):
            categories = ["Toutes les catégories"] + self.db.recuperer_categories()
            self.combo_category_filter.configure(values=categories)
            if self.current_category_filter in categories:
                self.combo_category_filter.set(self.current_category_filter)
            else:
                self.current_category_filter = "Toutes les catégories"
                self.combo_category_filter.set("Toutes les catégories")


        # 5. Rafraîchir le panier 
        if self.current_user_role in ("Vendeur", "Gérant"):
            self.rafraichir_panier_display()

        # 6. Rafraîchir le journal de stock si l'onglet est visible
        if hasattr(self, 'tree_journal_stock'):
            self.rafraichir_journal_stock() 

    def rafraichir_panier_display(self): 
        """Mise à jour du Treeview du panier et du total."""
        if not hasattr(self, 'tree_panier'): return

        # Vider l'affichage
        for row in self.tree_panier.get_children():
            self.tree_panier.delete(row)

        total_general_cdf = 0

        # Remplir l'affichage
        items_to_remove = []
        for prod_id, qte_panier in self.panier.items():
            details = self.produits_details.get(prod_id)
            if details:
                # Vérification de la disponibilité du stock actuel
                stock_actuel = details['stock']
                if qte_panier > stock_actuel:
                    # Ajuster la quantité dans le panier si le stock est devenu insuffisant
                    if stock_actuel > 0:
                        self.panier[prod_id] = stock_actuel
                        qte_panier = stock_actuel
                        messagebox.showwarning("Stock Ajusté", f"La quantité de {details['nom']} dans le panier a été ajustée à {stock_actuel} en raison d'un stock insuffisant.")
                    else:
                        items_to_remove.append(prod_id)
                        continue # Passer à l'article suivant si stock est 0

                prix_u = details['prix']
                total_cdf = prix_u * qte_panier
                total_general_cdf += total_cdf
                
                self.tree_panier.insert("", tk.END, values=(
                    prod_id, 
                    details['nom'], 
                    qte_panier, 
                    f"{prix_u:.0f}", 
                    f"{total_cdf:.0f}"
                ), tags=(prod_id,))
            else:
                # L'article a été supprimé du stock
                items_to_remove.append(prod_id)

        # Retirer les articles qui ont été supprimés
        for prod_id in items_to_remove:
            del self.panier[prod_id]

        self.panier_total_label.configure(text=f"TOTAL GÉNÉRAL : {total_general_cdf:.0f} FC")
    
    def action_ajouter_au_panier(self):
        try:
            selection_complete = self.combobox_produits.get()
            if "AUCUN PRODUIT" in selection_complete:
                messagebox.showwarning("Erreur", "Aucun produit sélectionné.")
                return 

            prod_id_str = selection_complete.split(' | ')[0]
            prod_id = int(prod_id_str)
            qty_add = int(self.entry_vente_qty.get())

            if qty_add <= 0:
                messagebox.showwarning("Attention", "La quantité doit être positive.")
                return 

            details = self.produits_details.get(prod_id)
            if not details:
                messagebox.showerror("Erreur", "Produit introuvable. Rafraîchissez la liste.")
                return

            stock_actuel = details['stock']
            qte_deja_panier = self.panier.get(prod_id, 0)

            if qte_deja_panier + qty_add > stock_actuel:
                messagebox.showwarning("Stock insuffisant", f"Seulement {stock_actuel - qte_deja_panier} unités restantes en stock pour ce produit.")
                return 

            # Mise à jour du panier
            self.panier[prod_id] = qte_deja_panier + qty_add
            self.entry_vente_qty.delete(0, tk.END)
            self.entry_vente_qty.insert(0, "1")
            self.rafraichir_panier_display()

        except ValueError:
            messagebox.showerror("Erreur", "Veuillez entrer une quantité valide.")
        except Exception as e:
            messagebox.showerror("Erreur", f"Erreur lors de l'ajout au panier: {e}")
            
    def action_retirer_du_panier(self):
        selected_item = self.tree_panier.focus()
        if selected_item:
            # L'ID du produit est stocké dans le tag ou dans la première colonne
            item_values = self.tree_panier.item(selected_item, 'values')
            if item_values:
                prod_id = int(item_values[0])
                if prod_id in self.panier:
                    del self.panier[prod_id]
                    self.rafraichir_panier_display()
                
    def action_valider_panier(self):
        if not self.panier:
            messagebox.showwarning("Panier vide", "Le panier est vide. Ajoutez des articles pour valider la vente.")
            return

        confirmation = messagebox.askyesno(
            "Confirmation de Vente",
            f"Voulez-vous confirmer la vente de {len(self.panier)} articles pour un total de {self.panier_total_label.cget('text').split(':')[1].strip()} ?"
        )
        
        if not confirmation:
            return

        ventes_reussies = 0
        ventes_echouees = 0
        
        # Créer une copie car le stock peut changer pendant l'itération
        panier_copy = self.panier.copy() 
        
        for prod_id, quantite in panier_copy.items():
            success, message = self.db.faire_une_vente(prod_id, quantite)
            if success:
                ventes_reussies += 1
            else:
                ventes_echouees += 1 
                
        # Après la transaction, vider le panier en mémoire
        self.panier.clear()
        
        if ventes_reussies > 0:
            messagebox.showinfo("Vente Réussie", f"{ventes_reussies} article(s) vendu(s) avec succès. {ventes_echouees} échec(s).")
            self.rafraichir_listes() # Rafraîchit le stock affiché, le combobox et le panier
        elif ventes_echouees > 0: 
            # Ce cas arrive si la première vente a échoué
            messagebox.showerror("Erreur de Transaction", "Aucune vente n'a pu être complétée. Veuillez vérifier les stocks et recommencer.")
        else:
            # Ce cas est un garde-fou
            messagebox.showwarning("Attention", "Aucun article dans le panier après vérification.")

    def action_filtrer_ventes(self):
        date_debut = self.entry_date_debut.get()
        date_fin = self.entry_date_fin.get()
        
        for row in self.tree_historique.get_children():
            self.tree_historique.delete(row)

        ventes = self.db.recuperer_ventes(date_debut, date_fin)
        total_general = 0
        
        for vente in ventes:
            # vente = (date_vente, nom_produit, quantite, prix_unitaire_cdf, total_vente_cdf)
            # Affichage en CDF
            self.tree_historique.insert("", tk.END, values=(vente[0], vente[1], vente[2], f"{vente[3]:.0f}", f"{vente[4]:.0f}"))
            total_general += vente[4]
            
        # Affichage du total en CDF
        self.tree_historique.insert("", tk.END, values=("", "", "", "TOTAL VENTES :", f"{total_general:.0f}FC"), tags=('total',))
        self.tree_historique.tag_configure('total', background='#E0E0E0', font=('Arial', 10, 'bold'))
        
    def setup_interface_historique(self, tab_frame):
        filter_frame = ctk.CTkFrame(tab_frame)
        filter_frame.pack(pady=20, padx=20, fill="x")

        ctk.CTkLabel(filter_frame, text="Date Début (YYYY-MM-DD) :").grid(row=0, column=0, padx=10, pady=5, sticky="w")
        self.entry_date_debut = ctk.CTkEntry(filter_frame, width=150)
        self.entry_date_debut.grid(row=0, column=1, padx=10, pady=5, sticky="ew")

        ctk.CTkLabel(filter_frame, text="Date Fin (YYYY-MM-DD) :").grid(row=0, column=2, padx=10, pady=5, sticky="w")
        self.entry_date_fin = ctk.CTkEntry(filter_frame, width=150)
        self.entry_date_fin.grid(row=0, column=3, padx=10, pady=5, sticky="ew")

        btn_filter = ctk.CTkButton(filter_frame, text="🔍 Filtrer l'Historique", command=self.action_filtrer_ventes, fg_color="#3B8EDC", hover_color="#36719F")
        btn_filter.grid(row=1, column=0, columnspan=4, pady=10, padx=10, sticky="ew")

        filter_frame.grid_columnconfigure((1, 3), weight=1)

        tree_frame = ctk.CTkFrame(tab_frame)
        tree_frame.pack(pady=10, padx=20, fill="both", expand=True)
        
        self.tree_historique = ttk.Treeview(tree_frame, columns=("Date", "Produit", "Qté", "Prix U", "Total"), show='headings')
        self.tree_historique.heading("Date", text="Date Vente", anchor="center")
        self.tree_historique.heading("Produit", text="Produit", anchor="center")
        self.tree_historique.heading("Qté", text="Qté", anchor="center")
        self.tree_historique.heading("Prix U", text="Prix U (FC)", anchor="center")
        self.tree_historique.heading("Total", text="Total (FC)", anchor="center")
        
        self.tree_historique.column("Date", width=150, stretch=tk.NO)
        self.tree_historique.column("Produit", width=250, stretch=tk.YES)
        self.tree_historique.column("Qté", width=70, stretch=tk.NO)
        self.tree_historique.column("Prix U", width=100, stretch=tk.NO)
        self.tree_historique.column("Total", width=100, stretch=tk.NO)
        
        self.tree_historique.pack(side="left", fill="both", expand=True)

        scrollbar = ctk.CTkScrollbar(tree_frame, command=self.tree_historique.yview)
        scrollbar.pack(side="right", fill="y")
        self.tree_historique.configure(yscrollcommand=scrollbar.set)
        
        self.action_filtrer_ventes() # Chargement initial de l'historique (sans filtre)
        
        # Bouton d'export PDF
        btn_pdf = ctk.CTkButton(tab_frame, text="📥 Exporter Rapport PDF de Ventes", command=lambda: self.action_generer_rapport_ventes(self.db.recuperer_ventes(self.entry_date_debut.get(), self.entry_date_fin.get()), "Rapport de Ventes"), fg_color="#3498DB", hover_color="#2980B9")
        btn_pdf.pack(pady=(10, 20), padx=20, fill="x")

    def action_generer_rapport_ventes(self, data, titre):
        # ... (Logique de génération de PDF - inchangée)
        try:
            if not data:
                messagebox.showwarning("Export PDF", "Aucune donnée de vente à exporter.")
                return

            taux_cdf = self.db.get_taux_usd_cdf()
            
            # Utiliser filedialog pour choisir l'emplacement de sauvegarde
            filename = filedialog.asksaveasfilename(
                defaultextension=".pdf",
                filetypes=[("PDF files", "*.pdf")],
                initialfile=f"{titre}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            )
            
            if not filename:
                return # Annulé par l'utilisateur
            
            doc = SimpleDocTemplate(filename, pagesize=A4)
            elements = []
            styles = getSampleStyleSheet()
            
            # En-tête (inclure le taux)
            elements.append(Paragraph(titre, styles['h1']))
            elements.append(Paragraph(f"Taux de conversion utilisé : 1 USD = {taux_cdf:.2f} CDF", styles['h3']))
            elements.append(Paragraph(f"Généré par le système le {datetime.now().strftime('%d/%m/%Y à %H:%M')}", styles['Normal']))
            elements.append(Paragraph("<br/>", styles['Normal']))

            # Préparation des données pour la table PDF
            # Changement des entêtes de colonnes : CDF est la base, USD est la conversion
            data_table = [["Date", "Produit", "Qté", "Prix U (CDF)", "Total (CDF)", "Total (USD)"]]
            total_general_cdf = 0 # Le nouveau total de base
            total_general_usd = 0 

            # data contient (date_vente, nom, qte, prix_u_cdf, total_cdf)
            for date_vente, nom, qte, prix_u_cdf, total_cdf in data:
                # Conversion : CDF / Taux = USD
                try:
                    # La valeur en USD est la valeur CDF divisée par le taux
                    total_usd = total_cdf / taux_cdf
                except ZeroDivisionError:
                    total_usd = 0.0 # Éviter la division par zéro si le taux est 0

                total_general_cdf += total_cdf
                total_general_usd += total_usd

                # AJOUT DES VALEURS dans le tableau
                data_table.append([
                    date_vente.split(' ')[0],
                    nom,
                    qte,
                    f"{prix_u_cdf:.0f} FC",
                    f"{total_cdf:.0f} FC",
                    f"{total_usd:.2f} $" # Affichage en USD (2 décimales)
                ])

            # Ligne du total (mise à jour pour les deux devises)
            data_table.append(["", "", "", "TOTAL GÉNÉRAL :", 
                               f"{total_general_cdf:.0f} FC", # Total en CDF (Base)
                               f"{total_general_usd:.2f} $"]) # Total converti en USD

            # Configuration de la table (taille ajustée)
            table = Table(data_table, colWidths=[1.1*inch, 1.5*inch, 0.5*inch, 1*inch, 1*inch, 1.2*inch])
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -2), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                # Style pour la ligne TOTAL
                ('BACKGROUND', (0, -1), (-1, -1), colors.lightgrey),
                ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
                ('ALIGN', (3, -1), (-1, -1), 'RIGHT'),
            ]))
            
            elements.append(table)
            
            doc.build(elements)
            messagebox.showinfo("Export PDF", f"Rapport '{titre}' généré avec succès à l'emplacement:\n{filename}")
            
        except Exception as e:
            messagebox.showerror("Erreur PDF", f"Erreur lors de la génération du rapport : {e}")


    def setup_interface_journal_stock(self, tab_frame):
        ctk.CTkLabel(tab_frame, text="JOURNAL DES ENTRÉES DE STOCK", font=("Arial", 18, "bold")).pack(pady=(20, 10))
        ctk.CTkLabel(tab_frame, text="Historique des ajouts de stock par le gérant (traçabilité de l'inventaire).").pack(pady=(0, 10))

        # AJOUT: FRAME DE FILTRE
        filter_frame = ctk.CTkFrame(tab_frame)
        filter_frame.pack(pady=10, padx=20, fill="x")
        
        ctk.CTkLabel(filter_frame, text="Date Début (YYYY-MM-DD) :").grid(row=0, column=0, padx=10, pady=5, sticky="w")
        self.entry_journal_date_debut = ctk.CTkEntry(filter_frame, width=150)
        self.entry_journal_date_debut.grid(row=0, column=1, padx=10, pady=5, sticky="ew")

        ctk.CTkLabel(filter_frame, text="Date Fin (YYYY-MM-DD) :").grid(row=0, column=2, padx=10, pady=5, sticky="w")
        self.entry_journal_date_fin = ctk.CTkEntry(filter_frame, width=150)
        self.entry_journal_date_fin.grid(row=0, column=3, padx=10, pady=5, sticky="ew")
        
        # AJOUT: Bouton Filtrer
        btn_filter_journal = ctk.CTkButton(filter_frame, text="🔍 Filtrer les Entrées", 
                                           command=self.action_filtrer_journal_stock,
                                           fg_color="#3B8EDC", hover_color="#36719F")
        btn_filter_journal.grid(row=1, column=0, columnspan=4, pady=10, padx=10, sticky="ew")
        
        filter_frame.grid_columnconfigure((1, 3), weight=1)

        tree_frame = ctk.CTkFrame(tab_frame)
        tree_frame.pack(pady=10, padx=20, fill="both", expand=True)

        self.tree_journal_stock = ttk.Treeview(tree_frame, columns=("Date", "Produit", "Qté Ajoutée"), show='headings')
        self.tree_journal_stock.heading("Date", text="Date d'Entrée", anchor="center")
        self.tree_journal_stock.heading("Produit", text="Produit", anchor="center")
        self.tree_journal_stock.heading("Qté Ajoutée", text="Quantité Ajoutée", anchor="center")
        self.tree_journal_stock.column("Date", width=200, stretch=tk.NO)
        self.tree_journal_stock.column("Produit", width=300, stretch=tk.YES)
        self.tree_journal_stock.column("Qté Ajoutée", width=150, stretch=tk.NO)
        self.tree_journal_stock.pack(side="left", fill="both", expand=True)

        scrollbar = ctk.CTkScrollbar(tree_frame, command=self.tree_journal_stock.yview)
        scrollbar.pack(side="right", fill="y")
        self.tree_journal_stock.configure(yscrollcommand=scrollbar.set)

        # NOUVEAU: Bouton d'export PDF pour le journal de stock
        btn_pdf_stock = ctk.CTkButton(tab_frame, text="📥 Exporter Rapport PDF du Journal de Stock", command=self.action_generer_rapport_stock, fg_color="#3498DB", hover_color="#2980B9")
        btn_pdf_stock.pack(pady=(10, 20), padx=20, fill="x")
        
        self.rafraichir_journal_stock() # Appel initial

    def action_filtrer_journal_stock(self):
        """Action du bouton Filtrer du journal de stock."""
        # NOUVELLE MÉTHODE
        self.rafraichir_journal_stock()

    def rafraichir_journal_stock(self):
        if not hasattr(self, 'tree_journal_stock'): 
            return 
            
        for row in self.tree_journal_stock.get_children():
            self.tree_journal_stock.delete(row)
        
        # AJOUT: Récupérer les filtres de dates
        date_debut = None
        date_fin = None
        if hasattr(self, 'entry_journal_date_debut'):
            date_debut = self.entry_journal_date_debut.get()
            if not date_debut: date_debut = None
        if hasattr(self, 'entry_journal_date_fin'):
            date_fin = self.entry_journal_date_fin.get()
            if not date_fin: date_fin = None
            
        # MODIF: Passage des filtres à la méthode backend
        entrees = self.db.recuperer_journal_stock(date_debut, date_fin) 
        
        for date_entree, nom, quantite_ajoutee in entrees:
            self.tree_journal_stock.insert("", tk.END, values=(date_entree, nom, quantite_ajoutee))

    def action_generer_rapport_stock(self):
        try:
            date_debut = self.entry_journal_date_debut.get() if hasattr(self, 'entry_journal_date_debut') else None
            date_fin = self.entry_journal_date_fin.get() if hasattr(self, 'entry_journal_date_fin') else None
            data = self.db.recuperer_journal_stock(date_debut, date_fin) 
            
            if not data:
                messagebox.showwarning("Export PDF", "Aucune donnée d'entrée de stock à exporter.")
                return

            # Utiliser filedialog pour choisir l'emplacement de sauvegarde
            filename = filedialog.asksaveasfilename(
                defaultextension=".pdf",
                filetypes=[("PDF files", "*.pdf")],
                initialfile=f"Journal_Stock_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            )
            
            if not filename:
                return # Annulé par l'utilisateur
            
            doc = SimpleDocTemplate(filename, pagesize=A4)
            elements = []
            styles = getSampleStyleSheet()
            
            # En-tête
            elements.append(Paragraph("JOURNAL DES ENTRÉES DE STOCK", styles['h1']))
            elements.append(Paragraph(f"Période filtrée : {date_debut or 'Début'} à {date_fin or 'Fin'}", styles['h3']))
            elements.append(Paragraph(f"Généré par le système le {datetime.now().strftime('%d/%m/%Y à %H:%M')}", styles['Normal']))
            elements.append(Paragraph("<br/>", styles['Normal']))

            # Préparation des données pour la table PDF
            data_table = [["Date d'Entrée", "Produit", "Quantité Ajoutée"]]
            total_ajoute = 0 

            # data contient (date_entree, nom, quantite_ajoutee)
            for date_entree, nom, quantite_ajoutee in data:
                data_table.append([date_entree, nom, quantite_ajoutee])
                total_ajoute += quantite_ajoutee

            # Ligne du total
            data_table.append(["", "TOTAL ARTICLES AJOUTÉS :", total_ajoute])

            # Configuration de la table
            table = Table(data_table, colWidths=[1.5*inch, 3*inch, 1.5*inch])
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -2), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                # Style pour la ligne TOTAL
                ('BACKGROUND', (0, -1), (-1, -1), colors.lightgrey),
                ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ]))
            
            elements.append(table)
            
            doc.build(elements)
            messagebox.showinfo("Export PDF", f"Rapport 'Journal de Stock' généré avec succès à l'emplacement:\n{filename}")
            
        except Exception as e:
            messagebox.showerror("Erreur PDF", f"Erreur lors de la génération du PDF du journal de stock : {e}")

    def setup_interface_administration(self, tab_frame):
        main_scroll_frame = ctk.CTkScrollableFrame(tab_frame, label_text="")
        main_scroll_frame.pack(fill="both", expand=True)

        # -------------------- GESTION UTILISATEURS --------------------
        creation_frame = ctk.CTkFrame(main_scroll_frame)
        creation_frame.pack(pady=20, padx=20, fill="x")

        ctk.CTkLabel(creation_frame, text="CRÉER UN NOUVEL UTILISATEUR", font=("Arial", 18, "bold")).grid(row=0, column=0, columnspan=4, pady=10)

        ctk.CTkLabel(creation_frame, text="Nom d'utilisateur:").grid(row=1, column=0, padx=10, pady=5, sticky="w")
        self.user_entry_username = ctk.CTkEntry(creation_frame, width=150)
        self.user_entry_username.grid(row=1, column=1, padx=10, pady=5, sticky="ew")

        ctk.CTkLabel(creation_frame, text="Mot de passe:").grid(row=1, column=2, padx=10, pady=5, sticky="w")
        self.user_entry_password = ctk.CTkEntry(creation_frame, width=150, show="*")
        self.user_entry_password.grid(row=1, column=3, padx=10, pady=5, sticky="ew")

        ctk.CTkLabel(creation_frame, text="Rôle:").grid(row=2, column=0, padx=10, pady=5, sticky="w")
        self.user_combobox_role = ctk.CTkComboBox(creation_frame, values=["Gérant", "Vendeur"], width=150)
        self.user_combobox_role.set("Vendeur")
        self.user_combobox_role.grid(row=2, column=1, padx=10, pady=5, sticky="ew")

        btn_create_user = ctk.CTkButton(creation_frame, text="👤 Créer l'utilisateur", command=self.action_creer_utilisateur, fg_color="#1E8449")
        btn_create_user.grid(row=3, column=0, columnspan=4, pady=15, padx=10, sticky="ew")
        
        creation_frame.grid_columnconfigure((1, 3), weight=1)

        # Liste des utilisateurs
        ctk.CTkLabel(main_scroll_frame, text="UTILISATEURS ACTUELS", font=("Arial", 16, "bold")).pack(pady=(15, 5))
        
        user_list_frame = ctk.CTkFrame(main_scroll_frame)
        user_list_frame.pack(pady=10, padx=20, fill="x")
        
        self.tree_users = ttk.Treeview(user_list_frame, columns=("ID", "Nom", "Rôle"), show='headings')
        self.tree_users.heading("ID", text="ID", anchor="center")
        self.tree_users.heading("Nom", text="Nom d'utilisateur", anchor="center")
        self.tree_users.heading("Rôle", text="Rôle", anchor="center")

        self.tree_users.column("ID", width=50, stretch=tk.NO)
        self.tree_users.column("Nom", width=150, stretch=tk.YES)
        self.tree_users.column("Rôle", width=100, stretch=tk.NO)
        
        self.tree_users.pack(side="left", fill="x", expand=True)

        scrollbar_users = ctk.CTkScrollbar(user_list_frame, command=self.tree_users.yview)
        scrollbar_users.pack(side="right", fill="y")
        self.tree_users.configure(yscrollcommand=scrollbar_users.set)
        self.tree_users.bind('<<TreeviewSelect>>', self.selectionner_utilisateur)

        btn_delete_user = ctk.CTkButton(main_scroll_frame, text="❌ Supprimer l'utilisateur sélectionné", command=self.action_supprimer_utilisateur, fg_color="#C0392B", hover_color="#A93226")
        btn_delete_user.pack(pady=(5, 15), padx=20, fill="x")

        # Changement de mot de passe (pour l'utilisateur actuellement connecté uniquement)
        password_frame = ctk.CTkFrame(main_scroll_frame)
        password_frame.pack(pady=10, padx=20, fill="x")

        ctk.CTkLabel(password_frame, text="CHANGER MON MOT DE PASSE (Connecté)", font=("Arial", 18, "bold")).grid(row=0, column=0, columnspan=2, pady=10)
        ctk.CTkLabel(password_frame, text="Nouveau mot de passe:").grid(row=1, column=0, padx=10, pady=5, sticky="w")
        self.entry_new_password = ctk.CTkEntry(password_frame, width=200, show="*")
        self.entry_new_password.grid(row=1, column=1, padx=10, pady=5, sticky="ew")

        btn_change_pass = ctk.CTkButton(password_frame, text="🔒 Changer le mot de passe", command=self.action_changer_mot_de_passe, fg_color="#3498DB")
        btn_change_pass.grid(row=2, column=0, columnspan=2, pady=15, padx=10, sticky="ew")
        
        password_frame.grid_columnconfigure(1, weight=1)

        # -------------------- Section : Taux de Change --------------------
        separator_taux = ctk.CTkFrame(main_scroll_frame, height=2, fg_color="gray")
        separator_taux.pack(fill="x", padx=20, pady=20)
        
        taux_frame = ctk.CTkFrame(main_scroll_frame)
        taux_frame.pack(pady=10, padx=20, fill="x")

        ctk.CTkLabel(taux_frame, text="TAUX DE CONVERSION (USD vers CDF)", font=("Arial", 18, "bold")).grid(row=0, column=0, columnspan=2, pady=10)
        # Le taux stocké est le nombre de CDF par 1 USD
        ctk.CTkLabel(taux_frame, text="Taux (CDF pour 1 USD) :").grid(row=1, column=0, padx=10, pady=5, sticky="w")
        self.entry_taux_cdf = ctk.CTkEntry(taux_frame, width=200)
        self.entry_taux_cdf.grid(row=1, column=1, padx=10, pady=5, sticky="ew")
        self.entry_taux_cdf.insert(0, str(self.db.get_taux_usd_cdf()))

        btn_set_taux = ctk.CTkButton(taux_frame, text="🔄 Mettre à Jour le Taux", command=self.action_set_taux_cdf, fg_color="#8E44AD")
        btn_set_taux.grid(row=2, column=0, columnspan=2, pady=15, padx=10, sticky="ew")
        
        taux_frame.grid_columnconfigure(1, weight=1)

        # -------------------- SECTION SAUVEGARDE / RESTAURATION --------------------
        separator_backup = ctk.CTkFrame(main_scroll_frame, height=2, fg_color="gray")
        separator_backup.pack(fill="x", padx=20, pady=20)
        
        backup_frame = ctk.CTkFrame(main_scroll_frame)
        backup_frame.pack(pady=10, padx=20, fill="x")
        
        ctk.CTkLabel(backup_frame, text="SAUVEGARDE ET RESTAURATION", font=("Arial", 18, "bold")).grid(row=0, column=0, columnspan=2, pady=10)

        btn_sauvegarde = ctk.CTkButton(backup_frame, text="💾 Sauvegarder la Base de Données", command=self.action_sauvegarder_bdd, fg_color="#3498DB")
        btn_sauvegarde.grid(row=1, column=0, padx=10, pady=15, sticky="ew")

        btn_restauration = ctk.CTkButton(backup_frame, text="🔄 Restaurer la Base de Données", command=self.action_restaurer_bdd, fg_color="#F39C12")
        btn_restauration.grid(row=1, column=1, padx=10, pady=15, sticky="ew")
        
        backup_frame.grid_columnconfigure((0, 1), weight=1)


        self.rafraichir_utilisateurs() # Appel initial

    def rafraichir_utilisateurs(self):
        for row in self.tree_users.get_children():
            self.tree_users.delete(row)
        
        utilisateurs = self.db.recuperer_utilisateurs()
        
        for user_id, username, role in utilisateurs:
            self.tree_users.insert("", tk.END, values=(user_id, username, role), 
                                   tags=('self' if user_id == self.current_user_id else ''))
            
        self.tree_users.tag_configure('self', background='#2ECC71', foreground='white') # Marquer l'utilisateur actuel

    def action_creer_utilisateur(self):
        username = self.user_entry_username.get()
        password = self.user_entry_password.get()
        role = self.user_combobox_role.get()
        
        if not username or not password or len(password) < 4:
            messagebox.showerror("Erreur", "Nom d'utilisateur et mot de passe (min 4 caractères) sont requis.")
            return

        if self.db.creer_utilisateur(username, password, role):
            messagebox.showinfo("Succès", f"Utilisateur '{username}' ({role}) créé.")
            self.user_entry_username.delete(0, tk.END)
            self.user_entry_password.delete(0, tk.END)
            self.rafraichir_utilisateurs()
        else:
            messagebox.showerror("Erreur", "Le nom d'utilisateur existe déjà.")

    def action_supprimer_utilisateur(self):
        if not hasattr(self, 'utilisateur_selectionne_id') or self.utilisateur_selectionne_id is None:
            messagebox.showwarning("Suppression", "Veuillez sélectionner un utilisateur à supprimer.")
            return

        if int(self.utilisateur_selectionne_id) == self.current_user_id:
            messagebox.showerror("Erreur", "Vous ne pouvez pas supprimer l'utilisateur actuellement connecté.")
            return
            
        if int(self.utilisateur_selectionne_id) == 1:
            messagebox.showerror("Erreur", "Vous ne pouvez pas supprimer l'utilisateur Gérant initial.")
            return

        confirmation = messagebox.askyesno(
            "Confirmation de Suppression",
            f"Êtes-vous sûr de vouloir supprimer l'utilisateur ID {self.utilisateur_selectionne_id} ({self.utilisateur_selectionne_nom}) ?"
        )
        
        if confirmation:
            if self.db.supprimer_utilisateur(int(self.utilisateur_selectionne_id)):
                messagebox.showinfo("Succès", f"Utilisateur ID {self.utilisateur_selectionne_id} supprimé.")
                self.utilisateur_selectionne_id = None
                self.utilisateur_selectionne_nom = None
                self.rafraichir_utilisateurs()
            else:
                 messagebox.showerror("Erreur", "Impossible de supprimer cet utilisateur.")

    def action_sauvegarder_bdd(self):
        backup_path = self.db.sauvegarder_bdd()
        if backup_path:
            messagebox.showinfo("Sauvegarde Réussie", f"La base de données a été sauvegardée dans : {backup_path}")
        else:
            messagebox.showerror("Erreur de Sauvegarde", "Une erreur est survenue lors de la sauvegarde de la base de données.")

    def action_restaurer_bdd(self):
        confirmation = messagebox.askyesno(
            "Confirmation de Restauration",
            "ATTENTION: Ceci écrasera la base de données actuelle.\n"
            "Êtes-vous sûr de vouloir continuer la restauration ?"
        )
        if not confirmation:
            return

        backup_filepath = filedialog.askopenfilename(
            title="Sélectionner le Fichier de Sauvegarde (.db)",
            filetypes=(("Fichiers de base de données SQLite", "*.db"), ("Tous les fichiers", "*.*"))
        )
        if not backup_filepath:
            return 

        success = self.db.restaurer_bdd(backup_filepath)
        if success:
            messagebox.showinfo("Restauration Réussie", "La base de données a été restaurée avec succès. Toutes les listes vont être rafraîchies.")
            self.rafraichir_listes()
            self.rafraichir_utilisateurs()
        else:
            messagebox.showerror("Erreur de Restauration", "Une erreur est survenue lors de la restauration.\n"
                                "Veuillez vérifier que le fichier sélectionné est valide et non corrompu.")

    def selectionner_utilisateur(self, event):
        selected_item = self.tree_users.focus()
        if selected_item:
            values = self.tree_users.item(selected_item, 'values')
            self.utilisateur_selectionne_id = values[0]
            self.utilisateur_selectionne_nom = values[1]

    def action_changer_mot_de_passe(self):
        new_password = self.entry_new_password.get()
        
        if len(new_password) < 4:
            messagebox.showerror("Erreur", "Le nouveau mot de passe doit contenir au moins 4 caractères.")
            return

        confirmation = messagebox.askyesno(
            "Confirmation de Changement",
            "Êtes-vous sûr de vouloir changer votre mot de passe ?"
        )
        
        if confirmation:
            self.db.changer_mot_de_passe(self.current_user_id, new_password)
            messagebox.showinfo("Succès", "Votre mot de passe a été mis à jour avec succès.")
            self.entry_new_password.delete(0, tk.END)

    def action_set_taux_cdf(self):
        try:
            nouveau_taux = float(self.entry_taux_cdf.get())
            if nouveau_taux <= 0:
                raise ValueError
                
            self.db.set_taux_usd_cdf(nouveau_taux)
            messagebox.showinfo("Succès", f"Le taux de conversion (CDF par 1 USD) a été mis à jour à {nouveau_taux:.2f}.")
            self.entry_taux_cdf.delete(0, tk.END)
            self.entry_taux_cdf.insert(0, str(nouveau_taux))

        except ValueError:
            messagebox.showerror("Erreur", "Veuillez entrer une valeur numérique positive pour le taux.")


if __name__ == "__main__":
    # Configurer l'apparence par défaut (Style bleu CustomTkinter)
    ctk.set_appearance_mode("System")  # Modes: "System", "Dark", "Light"
    ctk.set_default_color_theme("blue")  # Thèmes: "blue", "green", "dark-blue"

    root = ctk.CTk()
    app = ApplicationEcommerce(root)
    root.mainloop()