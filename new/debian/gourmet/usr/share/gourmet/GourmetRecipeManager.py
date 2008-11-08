#!/usr/bin/env python
import gtk.glade, gtk, gobject, os.path, time, os, sys, re, threading, gtk.gdk, Image, StringIO, pango, string, keyEditor
import printer

# UNCOMMENT THE FOLLOWING IMPORT STATEMENTS FOR CX_FREEZE
# stuff that shouldn't be necessary but may be:
#import pygtk, atk, gtk._gtk, pango #gtk stuff
#import Image #PIL stuff
# stuff that is definitely necessary:
#import codecs, encoding, encoding.string_search, encoding.utf_8 #encoding stuff 
#import defaults_en,defaults_en,defaults_en_GM,defaults_es #stuff imported with __import__

import prefs, shopgui, reccard, convertGui, fnmatch
import rxml_to_metakit, rmetakit, convert, exporter, importer, mealmaster_importer, WidgetSaver, version
import mastercook_importer
import dialog_extras as de
import treeview_extras as te
from get_pixbuf_from_file import get_pixbuf_from_jpg
from gdebug import *
from gglobals import *
from recindex import RecIndex
import recipe_emailer
import locale, gettext
_ = gettext.gettext
if use_threads:
    import GourmetThreads as gt
else:
    import GourmetFauxThreads as gt

locale.setlocale(locale.LC_ALL,'')
DIR = os.path.join(datad,'i18n')
gettext.bindtextdomain('gourmet',DIR)
gettext.textdomain('gourmet')
gettext.install('gourmet',DIR,unicode=1)


HTM = _('HTML Web Page (Creates a new Folder)')
MMF = _('Mealmaster file')
TXT = _('Plain Text')
RTF = _('RTF')
GXML = _('Gourmet XML File')
MX2 = _('Mastercook XML File')

try:
    import rtf_exporter
    rtf=True
except ImportError:
    debug('No RTF support',0)
    rtf=False

        
        
class RecGui (RecIndex):
    """This is the main application."""
    def __init__ (self,file=None,splash_label=gtk.Label()):
        try:
            import gnome
            gnome.program_init(version.appname,version.version)
        except ImportError:
            pass
        if debug_level > 0:
            debug("Debug level: %s"%debug_level, debug_level)
        self.splash_label = splash_label
        debug("__init__ (self,file=None):",5)
        self.update_splash(_("Loading window preferences..."))
        self.prefs = prefs.Prefs()
        self.update_splash(_("Loading graphical interface..."))        
        gtk.glade.bindtextdomain('gourmet',DIR)
        gtk.glade.textdomain('gourmet')
        debug("gladebase is: %s"%gladebase,1)
        self.glade = gtk.glade.XML(os.path.join(gladebase,'app.glade'))
        #set_accel_paths(self.glade, ['menubar3'])
        #self.settings = gtk.settings_get_default()
        #self.settings.set_property('gtk-can-change-accels',True)
        self.pop = self.glade.get_widget('rlmen')
        self.app = self.glade.get_widget('app')
        self.pauseButton = self.glade.get_widget('pauseButton')
        self.stopButton = self.glade.get_widget('stopButton')
        # this dictionary will let us keep track of what we connect o
        # the pause button so we can later disconnect it.
        self.pauseButton.connect('clicked',self.pause_cb)
        self.stopButton.connect('clicked',self.stop_cb)
        # a thread lock for import/export threads
        self.lock = gt.get_lock()
        # configuration stuff
        self.conf = []
        self.conf.append(WidgetSaver.WindowSaver(self.app,
                                                 self.prefs.get('app_window',
                                                                {}),
                                                 show=False))
        self.prog = self.glade.get_widget('progressbar')
        self.selected = gtk.TRUE
        self.act_on_row_widgets = [self.glade.get_widget('rlViewRecButton'),
                                   self.glade.get_widget('rlViewRecMenu'),
                                   self.glade.get_widget('rlShopRecButton'),
                                   self.glade.get_widget('rlShopRecMenu'),
                                   self.glade.get_widget('rlDelRecButton'),
                                   self.glade.get_widget('rlDelRecMenu'),
                                   self.glade.get_widget('email_menu_item'),
                                   self.glade.get_widget('print_menu_item'),
                                   ]

        #self.file = {'db':'recs.db'}
        #self.file = {'xml':'recs.xml'}
        #self.file = {'mmf' : 'mealmaster.mmf'}
        if not file:
            self.file={'db':os.path.join(gourmetdir,'recipes.mk')}
        elif type(file)==type(""):
            self.file={self.guess_type(file):file}
        else:
            self.file=file
        self.rtcolsdic={}
        for a,l,w in REC_ATTRS:
            self.rtcolsdic[a]=l
        self.rtcols=map(lambda r: r[0], REC_ATTRS)
        self.update_splash(_("Loading recipe database..."))
        self.init_recipes(**self.file)
        self.update_splash(_("Setting up recipe index..."))
        RecIndex.__init__(self, model=self.rmodel, glade=self.glade, rd=self.rd, rg=self)
        self.pauseid = self.stat.get_context_id('pause')
        self.rectree.connect("popup-menu",self.popup_rmenu)#self.recTreeSelectRec)
        self.rectree.connect("button-press-event",self.rectree_click_cb)
        self.glade.signal_autoconnect({
            'newRec' : self.newRecCard,
            'shopHide' : self.sl.hide,
            'showShop' : self.sl.show,
            'showList' : lambda *args: self.app.present(),            
            'new' : self.new,
            'open': self.open,
            'defaultsave': self.save_default,
            'export' : self.exportg,
            'import' : self.importg,
            'quit' : self.quit,
            'about' : self.show_about,
            'rl_viewrec' : self.recTreeSelectRec,
            'rl_shoprec' : self.recTreeShopRec,
            'rl_delrec': self.recTreeDeleteRec,
            'colPrefs': self.configureColDialog,
            'unitConverter': self.showConverter,
            'ingKeyEditor': self.showKeyEditor,
            'print':self.print_recs,
            'email':self.email_recs,
            'email_prefs':self.email_prefs,
#            'shopCatEditor': self.showShopEditor,            
            })
        self.rc={}
        self.updateViewMenu()
        ## make sure the focus is where it ought to be...
        self.app.present()
        self.srchentry.grab_focus()
        self.update_splash(_("Done!"))
        # used on imports to make filtering wait until
        # we are all done.
        self.wait_to_filter=False
        self.threads = 0
        
    def update_splash (self, text):
        """Update splash screen on startup."""
        debug("Setting splash text: %s"%text,3)
        self.splash_label.set_text(text)
        while gtk.events_pending():
            gtk.main_iteration()
        
    def del_rc (self, id):
        """Delete recipe with ID=id"""
        if self.rc.has_key(id):
            del self.rc[id]
        self.updateViewMenu()
        
    def viewMenu (self):
        """Build a _View menu based on recipes currently
        opened in recipe cards."""
        m=gtk.Menu()
        ri=gtk.MenuItem(_('Recipe _Index'))
        sh=gtk.MenuItem(_('Shopping _List'))
        separator=gtk.MenuItem()
        ri.connect('activate',lambda *args: self.app.present())
        sh.connect('activate',self.sl.show)
        m.append(ri)
        ri.show()
        m.append(sh)
        sh.show()
        m.append(separator)
        separator.show()
        for rc in self.rc.values():
            i=gtk.MenuItem("_%s"%rc.current_rec.title)
            i.connect('activate',rc.show)
            m.append(i)
            i.show()
        return m

    def updateViewMenu (self):
        """Update view menus in all open windows."""
        glades=[self.glade, self.sl.glade]
        for r in self.rc.values():
            glades.append(r.glade)
        for glade in glades:
            menu=self.viewMenu()
            vmi=glade.get_widget('view_menu_item')
            vmi.set_submenu(menu)
    
    def show_about (self, *args):
        """Show information about ourselves, using GNOME's
        nice interface if available."""
	
        debug("show_about (self, *args):",5)
        description=version.description
        copyright=version.copyright
        appname=version.appname
        myversion=self.version
        authors=["Thomas M. Hinkle <Thomas_Hinkle@alumni.brown.edu>", _("Roland Duhaime (Windows porting assistance)")]
        website="http://grecipe-manager.sourceforge.net"
        documenters=None
        translator=_("translator-credits")
        # translator's should translate the string 'translator-credits'
        # If we're not using a translatino, then this isn't shown
        if translator == "translator-credits":
            translator = ""
        comments=None
        logo=gtk.gdk.pixbuf_new_from_file(os.path.join(imagedir,"gourmet_logo.png"))
        try:
            import gnome.ui
            # to test the non-GNOME hack on a GNOME system,
            # uncomment the following line
            # import asdflkjasdf
            args = [appname,
                    myversion,
                    copyright,
                    description,
                    authors,
                    comments,
                    translator,
                    logo]
            if not translator:
                args = args[0:5] + [None] + args[6:]
            about= gnome.ui.About(*args)
            try:
                about.set_website(website) #will be available in 2.6
            except AttributeError:
                debug('No website available in "about" with this version of gtk/gnome',2)
                c=about.get_property('comments')
                c += _("\nWebsite: %s")%website
                about.set_property('comments',c)
                pass
            about.show()
        except ImportError:
            sublabel = '%s\n%s'%(copyright,description)
            for a in authors:
                sublabel += '\n%s'%a
            if translator:
                sublabel += _('\nTranslated by: %s')%translator
            if website:
                sublabel += _('\nWebsite: %s')%website
            de.show_message(label='%s %s'%(appname,myversion),
                            sublabel=sublabel)
            
    def show_pause_button (self, thread, message=_("Import paused"),
                           stop_message=_("Stop import")):
        self.pause_message = message
        self.stop_message = stop_message
        self.thread = thread
        self.pauseButton.show()
        self.stopButton.show()

    def quit (self, *args):
        """Close down shop, giving user option of saving changes and
        saving our window prefs for posterity."""
        debug("quit (self, *args):",5)

        for c in self.conf:
            c.save_properties()
        a=self.glade.get_widget('app')
        saved= not self.rd.changed
        saveMe=False
        for r in self.rc.values():
            for c in r.conf:
                c.save_properties()
            if r.edited and de.getBoolean(parent=self.app,
                                             label=_("Save your edits to %s")%r.current_rec.title):
                r.saveEditsCB()
                saveMe=True
            else: r.edited=False # in case someone else checks this (e.g. reccard on close)
        for conf in self.sl.conf:
            conf.save_properties()
        self.prefs.save()
        threads=threading.enumerate()
        if len(threads) > 1:
            msg = "Another process is in progress"
            for t in threads:
                if "import" in t.getName(): msg = _("An import is in progress.")
                if "export" in t.getName(): msg = _("An export is in progress.")
                if "delete" in t.getName(): msg = _("A delete is in progress.")
            quit_anyway = de.getBoolean(label=msg,
                                        sublabel=_("Exit program anyway?"),
                                        custom_yes={'stock':gtk.STOCK_QUIT},
                                        custom_no=_("Don't exit!"), cancel=False)
            if quit_anyway:
                for t in threads:
                    if t.getName() !='MainThread':
                        try:
                            t.terminate()
                        except:
                            debug("Unable to terminate thread %s"%t,5)
                            return True
            else:
                return True
        if saveMe:
            self.save_default()
        elif not saved:
            check=de.getBoolean(label=_("Save database before quitting?"), parent=self.app.get_toplevel(),cancel_returns="CANCEL")
            if check=='CANCEL': return True
            elif check: self.save_default()
        for r in self.rc.values():
            r.widget.destroy()
        self.sl.widget.destroy()
        a.destroy()
        gtk.main_quit()

    def new (self, *args):
        debug("new (self, *args):",5)
        self.init_recipes()

    def guess_type (self, filestr):
        """Handed a file representing recipes,
        guess which type it is."""
        debug("guess_type (self, filestr):",5)
        if re.search("\.(db|mk)$",filestr):
            return "db"
        elif re.search("\.xml$",filestr):
            return "xml"
        elif re.search("\.mm.$",filestr):
            return "mmf"
        else: return "db"
        
    def open (self, *args):
        debug("open (self, *args):",5)
        f = de.select_file()
        debug("opening %s"%f, 1)
        if f:
            t = self.guess_type(f)
            ## we should probably do better than looking at extensions
            ## eventually **FIX ME**
            if t=="db":
                self.init_recipes(db=f)
            elif t=="xml":
                self.init_recipes(xml=f)
            elif t=="mmf":
                self.init_recipes(mmf=f)
            else:
                self.message(_("I can't determine the type of file %s")%f)

    def init_recipes (self, xml=None, db=None, mmf=None, defaultxml='recs.xml'):
        debug("init_recipes (self, xml=None, db=None, mmf=None, defaultxml='recs.xml'):        ",5)
        if xml:
            self.xtm = rxml_to_metakit.converter(xml)
            self.rd = self.xtm.db
        elif db:
            self.rd = rmetakit.recipeManager(db)
        elif mmf:
            self.rd = rmetakit.recipeManager()
            mealmaster_importer.mmf_importer(self.rd, filename=mmf)
        else:
            raise "No file specified"
        # connect hooks to modify our view whenever and
        # whenceever our recipes are updated...
        self.rd.modify_hooks.append(self.update_rec_iter)
        self.rd.add_hooks.append(self.new_rec_iter)
        self.rd.delete_hooks.append(self.delete_rec_iter)
        # a flag to make deleting multiple recs
        # more efficient...
        self.doing_multiple_deletions=False
        #self.conv = rmetakit.mkConverter(self.rd)
        self.conv = convert.converter()
        # we'll need to hand these to various other places
        # that want a list of units.
        self.umodel = convertGui.UnitModel(self.conv)
        self.inginfo = reccard.IngInfo(self.rd)
        self.create_rmodel(self.rd.rview)
        self.sl = shopgui.ShopGui(self, conv=self.conv)
        self.sl.hide()

    def selection_changed (self, selected=gtk.FALSE):
        if selected != self.selected:
            if selected: self.selected=gtk.TRUE
            else: self.selected=gtk.FALSE
            for w in self.act_on_row_widgets:
                w.set_sensitive(self.selected)

    def rectree_click_cb (self, tv, event):
        debug("rectree_click_cb (self, tv, event):",5)
        if event.button==3:
            self.popup_rmenu()
            return gtk.TRUE
        if event.button==1 and event.type ==gtk.gdk._2BUTTON_PRESS:
            self.recTreeSelectRec()

    def reset_rtree (self):
        debug("reset_rtree (self):",5)
        #self.rmodel=self.create_rmodel(self.rd.rview)
        #self.rectree.set_model(self.rmodel)
        self.update_rmodel(self.rd.rview)
        self.search()
        self.selection_changed()
        self.set_reccount()
        #for r in rview:
        #    if not r.id in ids:
        #        # if we're already there...
        #        iter=self.rmodel.append(None)
        #        self.set_iter_from_rec(r,iter)

    def new_rec_iter (self, rec):
        debug("new_rec_iter called",5)
        iter = self.rmodel.append(None)
        self.set_iter_from_rec(rec,iter)

    def delete_rec_iter (self, rec):
        # a simpler, but less correct solution
        # is to simply make deleted item invisible.
        #self.visible.remove(rec.id)
        if self.doing_multiple_deletions: return
        for row in self.rmodel:
            if row[0].id==rec.id:
                debug("delete_rec_iter found the row to delete",5)
                dbg = ""
                for r in row:
                    dbg += str(r)
                    dbg += " | "
                debug("delete_rec_iter acting on: %s"%dbg,5)
                # this seems to be necessary to prevent
                # a segfault on removing the last iter
                self.rectree.set_model(empty_model)
                row.model.remove(row.iter)
                self.rectree.set_model(self.rmodel_sortable)
                debug('delete_rec_iter removed recipe with ID %s'%rec.id,2)

        debug('delete_rec_iter couldn\'t find recipe with ID %s'%rec.id,1)

    def update_rec_iter (self, rec):
        # if r is already in our treeModel, we update values.
        # otherwise, we add it.
        debug("update_rec_iter called",5)
        for row in self.rmodel:
            recobj = row[0]
            if recobj.id == rec.id:
                row[0]=rec
                if rec.thumb:
                    row[1]=get_pixbuf_from_jpg(rec.thumb)
                else:
                    row[1]=None                
                n = 2
                for c in self.rtcols:
                    row[n]=str(getattr(rec,c))
                    n+=1
                debug("update_rec_iter done!, id=%s"%rec.id,)
                return
        else: self.new_rec_iter(rec)
    
    def set_iter_from_rec (self, r, iter, visible=gtk.TRUE):
        """Handed a rec and an iter, set the row values appropriately."""
        self.rmodel.set_value(iter, 0, r)
        if r.thumb:
            self.rmodel.set_value(iter, 1, get_pixbuf_from_jpg(r.thumb))
        else:
            self.rmodel.set_value(iter, 1, None)
        n = 2
        for c in self.rtcols:
            debug("setting column %s (n=%s)"%(c,n),5)
            self.rmodel.set_value(iter, n, str(getattr(r,c)))
            n += 1

    def create_rmodel (self, rview):
        debug("create_rmodel (self, rview):",5)
        # we start with our recipe object and our image
        mod = [gobject.TYPE_PYOBJECT,gtk.gdk.Pixbuf]
        # we add columns for all attributes...
        for n in self.rtcols:
            mod.append(gobject.TYPE_STRING)
        self.rmodel = apply(gtk.TreeStore,mod)
        # now we add our recipes
        for r in rview:
            self.new_rec_iter(r)

    def recTreeDeleteRecCB (self, *args):
        """Make a watch show up (this can be slow
        if lots of recs are selected!"""
        #gtk.app.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))
        #gtk.idle_add(self.recTreeDeleteRec)
        # this seems broken
        self.recTreeDeleteRec()
        
    def recTreeDeleteRec (self, *args):
        debug("recTreeDeleteRec (self, *args):",5)
        mod,rr=self.rectree.get_selection().get_selected_rows()
        recs = map(lambda path: mod[path][0],rr)
        expander=None
        bigmsg = _("Delete recipes?")
        if len(recs) == 1:
            bigmsg = _("Delete recipe?")
            msg = _("Are you sure you want to delete the recipe <i>%s</i>")%recs[0].title
        elif len(recs) < 5:
            msg = _("Are you sure you want to delete the following recipes?")
            for r in recs:
                msg += "\n<i>%s</i>"%r.title
        else:
            msg = _("Are you sure you want to delete the %s selected recipes?")%len(recs)
            tree = te.QuickTree(map(lambda r: r.title, recs))
            expander = [_("See recipes"),tree]
        if de.getBoolean(parent=self.app,label=bigmsg,sublabel=msg,expander=expander):
            self.doing_multiple_deletions=True
            self.iters_to_remove=[]
            for p in rr:
                # we remove by hand...
                iter = self.rmodel_sortable.get_iter(p)
                child = self.rmodel_sortable.convert_iter_to_child_iter(None, iter)
                grandchild = self.rmodel_filter.convert_iter_to_child_iter(child)
                self.iters_to_remove.append(grandchild)
            self.iters_to_remove.sort()
            self.iters_to_remove.reverse()
            self.rectree.set_model(empty_model)
            for i in self.iters_to_remove:
                self.rmodel.remove(i)
            self.rectree.set_model(self.rmodel_sortable)
            def show_pause (t):
                gt.gtk_enter()
                self.show_pause_button(t,message=_('Deletion paused'), stop_message=_("Stop deletion"))
                gt.gtk_leave()
            def save_delete_hooks (t):
                self.saved_delete_hooks = self.rd.delete_hooks[0:]
                self.rd.delete_hooks = []
            def restore_delete_hooks (t):
                self.rd.delete_hooks = self.saved_delete_hooks
            pre_hooks = [
                lambda *args: self.lock.acquire(),
                save_delete_hooks,
                show_pause,
                ]
            post_hooks = [
                restore_delete_hooks,
                self.cleanup_pause,
                lambda *args: self.lock.release()]
            t=gt.SuspendableThread(gt.SuspendableDeletions(self, recs),
                                name='delete',
                                pre_hooks = pre_hooks,
                                post_hooks = post_hooks)
            if self.lock.locked_lock():
                de.show_message(label=_('An import, export or deletion is running'),
                                sublabel=_('The recipes will be deleted once the other process is finished.')
                                )
            debug('PRE_HOOKS=%s'%t.pre_hooks,1)
            debug('POST_HOOKS=%s'%t.post_hooks,1)
            debug('rd.add_hooks=%s'%self.rd.add_hooks,1)
            gt.gtk_leave()
            t.start()
            gt.gtk_enter()
            
    def delete_rec (self, rec):
        debug("delete_rec (self, rec): %s"%rec,5)
        debug("does %s have %s"%(self.rc,rec.id),5)
        if self.rc.has_key(rec.id):
            debug("Getting rid of open recipe card window.",2)
            w=self.rc[rec.id].widget
            self.rc[rec.id].hide()
            w.destroy()
            self.updateViewMenu()
        if hasattr(rec,'id') and rec.id:
            titl = rec.title
            debug('deleting recipe',5)
            self.rd.delete_rec(rec.id)
            if not self.doing_multiple_deletions:
                gt.gtk_enter()
                self.message(_("Deleted recipe %s")%titl)
                self.doing_multiple_deletions=False
                gt.gtk_leave()
        else:
            debug("%s %s does not have an ID!"%(rec,rec.title),2)
        debug("returning None",2)
        return None

    def email_recs (self, *args):
        debug('email_recs called!',1)
        recs = self.recTreeSelectedRecs()
        d=recipe_emailer.EmailerDialog(recs, self.rd, self.prefs, self.conv)
        d.setup_dialog()
        d.email()

    def email_prefs (self, *args):
        d = recipe_emailer.EmailerDialog([],None,self.prefs,self.conv)
        d.setup_dialog(force=True)

    def print_recs (self, *args):
        recs = self.recTreeSelectedRecs()
        printer.RecRenderer(self.rd, recs,
                            dialog_title=_("Print %s Recipes"%len(recs)),
                            dialog_parent = self.app)

    def popup_rmenu (self, *args):
        debug("popup_rmenu (self, *args):",5)
        self.pop.popup(None,None,None,0,0)

    def newRecCard (self, *args):
        self.app.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))
        def show ():
            rc=reccard.RecCard(self)
            self.rc[rc.current_rec.id]=rc
            self.app.window.set_cursor(None)
        gtk.idle_add(show)

    def openRecCard (self, rec):
        if self.rc.has_key(rec.id):
            self.rc[rec.id].show()
        else:
            def show ():
                w=reccard.RecCard(self, rec)
                self.rc[rec.id]=w
                self.updateViewMenu()
                self.app.window.set_cursor(None)
            self.app.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))
            gtk.idle_add(show)
    def recTreeSelectRec (self, *args):
        debug("recTreeSelectRec (self, *args):",5)
        for rec in self.recTreeSelectedRecs():
            self.openRecCard(rec)

    def recTreeShopRec (self, *args):
        debug("recTreeShopRec (self, *args):",5)
        rr=self.recTreeSelectedRecs()
        #r = self.recTreeSelectedRec()
        for r in rr:
            if r.servings and r.servings != "None":
                debug("servings=%s"%r.servings,5)
                serv = de.getNumber(default=float(r.servings),
                                    label=_("Number of servings of %s to shop for")%r.title,
                                    parent=self.app.get_toplevel())
                if serv: mult = float(serv)/float(r.servings)
                else:
                    debug('getNumber cancelled',2)
                    return
            else:
                mult = de.getNumber(default=float(1),
                                    label=_("Multiply %s by: ")%r.title,
                                    parent=self.app.get_toplevel(),
                                    digits=2)
                if not mult:
                    mult = float(1)
            d=shopgui.getOptionalIngDic(self.rd.get_ings(r),mult)
            self.sl.addRec(r,mult,d)
            self.sl.show()

    def saveg (self, *args):
        debug("saveg (self, *args):",5)
        self.save(de.select_file())

    def save_default (self, *args):
        debug("save_default (self, *args):",5)
        self.save(**self.file)

    def save (self, file=None, db=None, xml=None):
        debug("save (self, file=None, db=None, xml=None):",5)
        if not xml and not db:
            if re.search(".xml$",file):
                xml=file
            else:
                db=file
        if xml:
            self.exportXML(file)
        else:
            self.rd.file=db
            self.rd.save()
            self.message(_("Saved!"))
            
    def message (self, msg):
        debug("message (self, msg): %s"%msg,5)
        self.stat.push(self.contid,msg)
        gtk.timeout_add(1500,self.flush_messages)

    def flush_messages (self, ret=False):
        debug("flush_messages (self):",5)
        self.stat.pop(self.contid)
        return ret

    def exportg (self, *args):        
        saveas_filters = [
                          [HTM,['text/html'],['']],
                          [MMF,['text/mmf'],['*.mmf','*.MMF']],
                          [TXT,['text/plain'],['*.txt','*.TXT']],      
                          [GXML,['text/xml'],['*.xml','*.XML']]
                          ]
        if rtf: saveas_filters.append([RTF,['application/rtf','text/rtf'],['*.rtf','*.RTF']]),
        ext = self.prefs.get('save_recipes_as','%sxml'%os.path.extsep)
        exp_directory = self.prefs.get('rec_exp_directory','~')
        file,exp_type=de.saveas_file(_("Export recipes"),
                                     filename="%s/%s%s"%(exp_directory,_('recipes'),ext),
                                     parent=self.app.get_toplevel(),
                                     filters=saveas_filters)
        if file:
            self.prefs['rec_exp_directory']=os.path.split(file)[0]
            self.prefs['save_recipes_as']=os.path.splitext(file)[1]
            expClass=None            
            post_hooks = [self.after_dialog_offer_url(exp_type,file)]
            if exp_type==HTM:
                prog = lambda prog: self.set_progress_thr(
                    prog,
                    _("total recipes. %i%% done creating web page.")%(prog*100)
                    )
                expClass = exporter.website_exporter(self.rd, self.rd.rview,
                                                     file, self.conv,
                                                     progress_func=prog)
                
            elif exp_type==MMF:
                prog = lambda prog: self.set_progress_thr(prog, _("total recipes. %i%% done exporting mealmaster file.")%(prog*100))
                expClass = exporter.ExporterMultirec(self.rd, self.rd.rview,
                                                     file, one_file=True, ext='mmf',
                                                     conv=self.conv, progress_func=prog,
                                                     exporter=exporter.mealmaster_exporter)
            elif exp_type==TXT:
                prog=lambda prog: self.set_progress_thr(
                    prog,
                    _("total recipes. %i%% done exporting text.")%(prog*100)
                    )
                expClass = exporter.ExporterMultirec(self.rd,self.rd.rview,file,
                                                     conv=self.conv, progress_func=prog)
            elif exp_type == RTF:
                prog = lambda prog: self.set_progress_thr(prog, _("total recipes. %i%% done creating RTF Document.")%(prog*100))
                expClass = rtf_exporter.rtf_exporter_multidoc(self.rd, self.rd.rview, out=file,
                                                              progress_func=prog)
            elif exp_type == GXML:
                prog = lambda prog: self.set_progress_thr(prog, _("total recipes. %i%% done exporting XML file.")%(prog*100))
                expClass = rxml_to_metakit.rview_to_xml(self.rd, self.rd.rview, file, progress_func=prog)
            if expClass:
                self.threads += 1
                def show_pause (t):
                    debug('showing pause button',1)
                    gt.gtk_enter()
                    self.show_pause_button(t,message=_('Export Paused'),stop_message=_("Stop export"))
                    gt.gtk_leave()
                pre_hooks = [show_pause]
                pre_hooks.insert(0, lambda *args: self.lock.acquire())
                post_hooks.append(lambda *args: self.reset_prog_thr())
                post_hooks.append(self.cleanup_pause)
                post_hooks.append(lambda *args: self.lock.release())
                t=gt.SuspendableThread(expClass, name='export%s'%self.threads,
                                    pre_hooks=pre_hooks,
                                    post_hooks=post_hooks)
                if self.lock.locked_lock():
                    de.show_message(label=_('An import, export or deletion is running'),
                                    sublabel=_('Your export will start once the other process is finished.'))
                debug('PRE_HOOKS=%s'%t.pre_hooks,1)
                debug('POST_HOOKS=%s'%t.post_hooks,1)                
                t.start()
            else:
                de.show_message(label=_('Gourmet cannot export file of type "%s"')%os.path.splitext(file)[1],
                                type=gtk.MESSAGE_ERROR)

    def import_pre_hook (self, *args):
        debug('import_pre_hook, gt.gtk_enter()',1)
        debug('about to run... %s'%self.rd.add_hooks[1:-1],1)
        gt.gtk_enter()

    def import_post_hook (self, *args):
        debug('import_post_hook,gt.gtk_leave()',5)
        gt.gtk_leave()
          
    def importg (self, *args):
        import_directory = "%s/"%self.prefs.get('rec_import_directory',None)
        XML_MATCH=['*.xml','*.gourmet']
        MMF_MATCH=['*.mmf','*.txt']
        MX2_MATCH=['*.mx2','*.xml']
        BOTH_MATCH = []
        BOTH_MATCH.extend(XML_MATCH)
        BOTH_MATCH.extend(MMF_MATCH)
        debug('show import dialog',0)
        file=de.select_file(
            _("Import Recipes"),
            filename=import_directory,
            filters=[
            [_('All importable files'),
             ['text/xml','application/xml','text/mealmaster','text/plain'],
             BOTH_MATCH],
            [GXML,
             ['text/xml','application/xml','text/plain'],
             XML_MATCH
             ],
            [MMF,
             ['text/mealmaster','text/plain'],
             MMF_MATCH
             ],
            [MX2,
             ['xml/mastercook','application/xml','text/xml','text/plain'],
             MX2_MATCH
             ],
            ],
            action=gtk.FILE_CHOOSER_ACTION_OPEN)
        if file:
            self.prefs['rec_import_directory']=os.path.split(file)[0]
            impClass = None
            pre_hooks = [lambda *args: self.inginfo.disconnect_manually()]
            post_hooks = [lambda *args: self.inginfo.reconnect_manually()]
            def test_patterns (patterns):
                if True in map(lambda p: fnmatch.fnmatch(file.lower(),p.lower()), patterns):
                    return True
            # if any of our XML patterns match...
            if test_patterns(XML_MATCH):
                impClass = rxml_to_metakit.converter(file,self.rd,threaded=True)
            elif test_patterns(MX2_MATCH):
                source=de.getEntry(label=_("Default source for recipes imported from %s")%file,
                                   default=os.path.split(file)[1], parent=self.app)
                impClass = mastercook_importer.converter(file,self.rd,
                                                         threaded=True,
                                                         progress=self.set_progress_thr)
            elif test_patterns(MMF_MATCH):
                source=de.getEntry(label=_("Default source for recipes imported from %s")%file,
                   default=os.path.split(file)[1], parent=self.app)
                impClass = mealmaster_importer.mmf_importer(filename=file,
                                                       rd=self.rd,
                                                       progress=self.set_progress_thr,
                                                       source=source,
                                                       threaded=True)
                post_hooks.append(lambda *args: debug('reset progress thread') or self.reset_prog_thr())            
            if impClass:                
                # we have to make sure we don't filter while we go (to avoid
                # slowing down the process too much).
                self.wait_to_filter=True
                pre_hooks.append(lambda *args: self.rd.add_hooks.insert(0,self.import_pre_hook))
                pre_hooks.append(lambda *args: self.rd.add_hooks.append(self.import_post_hook))
                self.threads += 1
                release = lambda *args: self.lock.release()
                post_hooks.extend([self.import_cleanup,
                                   self.cleanup_pause,
                                   release])
                def show_pause (t):
                    debug('showing pause button',5)
                    gt.gtk_enter()
                    self.show_pause_button(t)
                    gt.gtk_leave()
                pre_hooks.insert(0,show_pause)
                pre_hooks.insert(0, lambda *args: self.lock.acquire())
                t=gt.SuspendableThread(impClass,name="import%s"%self.threads,
                                   pre_hooks=pre_hooks, post_hooks=post_hooks)
                if self.lock.locked_lock():
                    de.show_message(label=_('An import, export or deletion is running'),
                                    sublabel=_('Your import will start once the other process is finished.'))
                debug('starting thread',2)
                debug('PRE_HOOKS=%s'%t.pre_hooks,1)
                debug('POST_HOOKS=%s'%t.post_hooks,1)                
                t.start()
            else:
                debug('GOURMET cannot import file %s'%file)

    def import_cleanup (self, *args):
        """Remove our threading hooks"""
        debug('import_cleanup!',1)
        self.rd.add_hooks.remove(self.import_pre_hook)
        self.rd.add_hooks.remove(self.import_post_hook)
        debug('hooks: %s'%self.rd.add_hooks,1)
        self.wait_to_filter=False
        gt.gtk_enter()
        self.lsrch=['','']
        self.search()
        gt.gtk_leave()

    def after_dialog_offer_url (self, linktype, file):
        url = "file:///%s"%file
        label = _("Export succeeded")
        if linktype == HTM:
            url += '/index.htm'
            linktype = _("webpage")
        sublabel = _("Exported %s to %s"%(linktype,file))
        return lambda *args: self.idle_offer_url(label, sublabel, url, True)

    def idle_offer_url (self, label, sublabl, url, from_thread):
        if from_thread:
            gt.gtk_enter()
        gtk.idle_add(lambda *args: self.offer_url(label,sublabl,url,True))
        if from_thread:
            gt.gtk_leave()
            
    def offer_url (self, label, sublabel, url, from_thread=False):
        if from_thread:
            gt.gtk_enter()
        d=de.messageDialog(label=label,
                           sublabel=sublabel,
                           cancel=False
                           )
        b = gtk.Button(stock=gtk.STOCK_JUMP_TO)
        b.connect('clicked',lambda *args: launch_url(url))
        d.vbox.pack_end(b,expand=False)
        b.show()
        d.run()
        if from_thread:
            gt.gtk_leave()

    def cleanup_pause (self, thread):
        debug('start: cleanup_pause',5)
        gt.gtk_enter()
        self.stopButton.hide()
        self.pauseButton.set_active(False)
        self.pauseButton.hide()
        gt.gtk_leave()

    def pause_cb (self, button, *args):
        if button.get_active():
            debug('Suspending thread from pause_cb',0)
            self.thread.suspend()
            self.stat.push(self.pauseid, self.pause_message)
            self.flusher = gtk.timeout_add(1000,lambda *args: self.flush_messages(True))
        else:
            self.stat.pop(self.pauseid)            
            gtk.timeout_remove(self.flusher)
            self.thread.resume()
            
    def stop_cb (self, *args):
        debug('Stop_cb called; pausing thread',1)
        self.thread.suspend()
        if de.getBoolean(label=self.stop_message):
            debug('Stopping thread from stop cb',0)
            self.thread.terminate()
        else:
            debug('Resuming thread: stop_cb cancelled',0)
            self.thread.resume()

    def reset_tree (self):
        self.create_rview(self.rd.rview)

    def reset_prog_thr (self):
        gt.gtk_enter()
        self.prog.set_fraction(0)
        self.set_reccount()
        gt.gtk_leave()
        
    def set_progress_thr (self, prog, message=_("Total Recipes (Importing...)")):
        debug("set_progress_thr (self, prog,msg): %s"%prog,5)
        gt.gtk_enter()
        self.prog.set_fraction(prog)
        self.stat.push(self.contid,"%s %s"%(len(self.rd.rview),message))
        gt.gtk_leave()

    def configureColDialog (self, *args):
        already_hidden=self.prefs.get('rectree_hidden_columns',None)
        def mapper (i):
            if i in already_hidden: return [i, False]
            else: return [i, True]
        options=map(lambda i: self.rtcolsdic[i], self.rtcols)
        options=map(mapper, options)
        pd = de.preferences_dialog(options=options, option_label=None, value_label=_("Show in Index View"),
                                   apply_func=self.configure_columns, parent=self.app)
        pd.show()

    def configure_columns (self, retcolumns):
        hidden=[]
        for c,v in retcolumns:
            if not v: hidden.append(c)
        self.rectree_conf.hidden=self.prefs['rectree_hidden_columns']=hidden
        self.rectree_conf.apply_visibility()

    def showConverter (self, *args):
        cg=convertGui.ConvGui(converter=self.conv, unitModel=self.umodel)

    def showKeyEditor (self, *args):
        ke=keyEditor.KeyEditor(rd=self.rd, rg=self)

#    def showShopEditor (self, *args):
#        se=shopEditor.ShopEditor(rd=self.rd,rg=self)

def set_accel_paths (glade, widgets, base='<main>'):
    """A convenience function. Hand us a function and set accel
    paths based on it."""
    for s in widgets:
        w=glade.get_widget(s)
        if type(w) == gtk.MenuItem: set_path_for_menuitem(w)
        else:
            for c in w.get_children():
                if type(c) == gtk.MenuItem:
                    set_path_for_menuitem(c,base)
                else:
                    debug("Can't handle %s"%c,1)

def set_path_for_menuitem (mi, base='<main>'):
    if mi.get_children():
        accelLab = mi.get_children()[0]
        l=accelLab.get_label().replace('_','')
        path = base + '/' + l
        #print 'setting path ',path
        mi.set_accel_path(path)
    sm = mi.get_submenu()
    if sm:
        sm.set_accel_path(path)
        for c in sm.get_children():
            set_path_for_menuitem(c,path)
    
    

def startGUI ():
    debug("startGUI ():",4)
    # show splash screen before we do anything...
    debug("showing splash screen...",1)    
    gt.gtk_threads_init()
    #gtk.threads_init()
    splash = gtk.Window()
    #splash.window_set_auto_startup_notification(gtk.FALSE)
    splash.set_property('decorated',gtk.FALSE)
    splash.set_position(gtk.WIN_POS_CENTER)
    splash.set_icon_from_file(os.path.join(imagedir,'recbox.png'))
    splash.set_title(_('Gourmet Recipe Manager starting up...'))
    pixbuf=gtk.gdk.pixbuf_new_from_file(os.path.join(imagedir,'splash.png'))
    pixmap, mask = pixbuf.render_pixmap_and_mask()
    width, height = pixmap.get_size()
    del pixbuf
    splash.set_app_paintable(gtk.TRUE)
    splash.resize(width, height)
    splash.realize()
    splash.window.set_back_pixmap(pixmap, gtk.FALSE)
    splash.label = gtk.Label(_("Starting gourmet..."))
    splash.label.set_alignment(0.5,1)
    splash.label.set_justify(gtk.JUSTIFY_CENTER)
    splash.label.show()
    splash.add(splash.label)
    del pixmap
    splash.show()
    splash.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))
    gt.gtk_enter()
    while gtk.events_pending():
        # show our GUI
        gtk.main_iteration()
    try:
        r=RecGui(splash_label=splash.label)
    except:
        splash.hide()
        while gtk.events_pending():
            gtk.main_iteration()
        #gtk.main_quit()
        raise
    debug('hiding splash screen.',1)
    splash.hide()
    gtk.main()
    gt.gtk_leave()
              
if __name__ == '__main__':
    startGUI()